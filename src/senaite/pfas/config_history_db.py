# -*- coding: utf-8 -*-
"""Configuration History in the shared results database (the table
`config_history` of qc_schema): one row per entry, its id, the columns the
history page filters on, and the entry itself as the JSON text it was
written as.

    insert(conn, entries, ignore=False)       the entries, in one statement each
    select(conn, store, key, since, until, limit, offset)   newest first
    count(conn, store, key, since, until)
    get(conn, eid)
    texts(conn, ids)                          {id: text} of the rows there
    checksum(pairs)                           sha256 over sorted (id, text)
    verify(pairs, conn)                       the copy of `pairs` in the table

Filters read as config_history always read them: a store or key filter is
exact (a key compared as text); `since` is the first stored "YYYY-MM-DD
HH:MM:SS" (UTC) kept, `until` the last, compared over its own length so a
bare date covers its whole day. Newest first is the entry's time, then the
order the rows were written in (two saves in one second).

Pure (sqlite3 only); Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import hashlib
import json

TABLE = "config_history"


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return u"%s" % (value if value is not None else u"")


def row_of(eid, text):
    """(id, at, who, store, key, entry) of one entry's JSON text."""
    text = _text(text)
    e = json.loads(text)
    return (_text(eid), _text(e.get("at")), _text(e.get("who")), _text(e.get("store")),
            _text(e.get("key")), text)


def insert(conn, pairs, ignore=False):
    """Write each (id, JSON text) of `pairs`. With `ignore`, a row whose id
    is there already is left as it is (a copy run again adds nothing)."""
    verb = "INSERT OR IGNORE" if ignore else "INSERT"
    n = 0
    for eid, text in pairs:
        cur = conn.execute("%s INTO %s (id, at, who, store, key, entry) VALUES (?, ?, ?, ?, ?, ?)"
                           % (verb, TABLE), row_of(eid, text))
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return n


def has_table(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (TABLE,)).fetchone() is not None


def _where(store, key, since, until):
    sql, args = [], []
    if store:
        sql.append("store = ?")
        args.append(_text(store))
    if key:
        sql.append("key = ?")
        args.append(_text(key))
    if since:
        sql.append("at >= ?")
        args.append(_text(since))
    if until:
        sql.append("substr(at, 1, ?) <= ?")
        args += [len(_text(until)), _text(until)]
    return (" WHERE " + " AND ".join(sql)) if sql else "", args


def select(conn, store=None, key=None, since=None, until=None, limit=None, offset=0):
    """The matching entries (dicts), newest first."""
    where, args = _where(store, key, since, until)
    sql = "SELECT entry FROM %s%s ORDER BY at DESC, rowid DESC" % (TABLE, where)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        args += [int(limit), int(offset or 0)]
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        args.append(int(offset))
    return [json.loads(r[0]) for r in conn.execute(sql, args)]


def count(conn, store=None, key=None, since=None, until=None):
    where, args = _where(store, key, since, until)
    return conn.execute("SELECT count(*) FROM %s%s" % (TABLE, where), args).fetchone()[0]


def get(conn, eid):
    row = conn.execute("SELECT entry FROM %s WHERE id = ?" % TABLE, (_text(eid),)).fetchone()
    return json.loads(row[0]) if row else None


def texts(conn, ids):
    """{id: JSON text} of the rows whose id is among `ids`."""
    out = {}
    ids = [_text(i) for i in ids]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for eid, text in conn.execute("SELECT id, entry FROM %s WHERE id IN (%s)"
                                      % (TABLE, ",".join("?" * len(chunk))), chunk):
            out[eid] = text
    return out


def checksum(pairs):
    """sha256 (hex) over the (id, text) pairs in id order: the same entries
    give the same sum on either side, one changed character another."""
    h = hashlib.sha256()
    for eid, text in sorted((_text(i), _text(t)) for i, t in pairs):
        h.update(eid.encode("utf-8"))
        h.update(b"\t")
        h.update(text.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def verify(pairs, conn):
    """Whether every (id, text) of `pairs` is in the table as it is, by count
    and checksum: {"ok", "count_source", "count_table", "sum_source",
    "sum_table", "missing", "different"}. Rows of the table that are not in
    `pairs` (entries written since) are not counted; `conn` None is a
    database not made yet."""
    pairs = [(_text(i), _text(t)) for i, t in pairs]
    there = texts(conn, [i for i, _t in pairs]) if conn is not None and has_table(conn) else {}
    copied = [(i, there[i]) for i, _t in pairs if i in there]
    missing = sorted(i for i, _t in pairs if i not in there)
    different = sorted(i for i, t in pairs if i in there and there[i] != t)
    out = {"count_source": len(pairs), "count_table": len(copied),
           "sum_source": checksum(pairs), "sum_table": checksum(copied),
           "missing": missing, "different": different}
    out["ok"] = (not missing and not different and out["count_source"] == out["count_table"]
                 and out["sum_source"] == out["sum_table"])
    return out
