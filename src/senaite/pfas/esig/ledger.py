# -*- coding: utf-8 -*-
"""The append-only, hash-chained signature ledger (one SQLite file).

Rows are never deleted and never updated, except that the seal columns fill
once. The chain is hash = sha256(prev + newline + entry), the first prev being
64 zeros. The UNIQUE key over (kind, record_id, record_hash, signer, meaning,
supersedes, withdraws) makes a replayed append return the row it already
made; the same signature naming another row it replaces or takes back is a
new row (a re-sign after a withdrawal, or after another signer's row
replaced it; a second withdrawal on the same content). supersedes and
withdraws are kept as text, '' when the entry names no row.

Inside Zope a row belongs to the transaction that signs it: append()
prepares the row (its seq, prev and hash chained onto the ledger's head and
onto the rows this transaction already prepared) and joins the transaction.
The rows are inserted at the transaction's vote, under the ledger's
exclusive lock, and committed at its finish, before any other resource
finishes; an abort, a failed vote anywhere or a rolled-back savepoint
writes nothing. A failed insert vetoes the commit, so nothing the signature
belongs to is committed without its row. The ledger's head moving under a
prepared row (another transaction signed first) is a ConflictError: the
request is retried and prepares its rows again, so the chain never forks
and the seq and hash a caller stored stay true. The reads in this module
see the rows this transaction prepared. Without a transaction package (the
worker, the verifier, a script with no Zope) a row is written at once.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import os
import sqlite3

from senaite.pfas.esig import canonical

DB_PATH = os.environ.get("PFAS_SIGNATURES_DB", "/data/qc/signatures.db")
GENESIS = "0" * 64
# a lot extension is QA's approval of a lot's new expiry (lot_extension.py);
# a CoC receipt is the corrected receipt date of a received CoC
# (coc_records), signed by the person who corrects it
KINDS = ("preparation", "batch_record", "certificate", "lot_extension", "coc_receipt")
MEANINGS = ("preparer", "reviewer", "authoriser", "released_interim",
            "superseded", "withdrawn", "qa_approved", "corrected")
# the seal worker rewrites its head file and seals new rows every tick (30
# s): ten minutes without either means it is not doing its work. The
# Signatures page and the verifier both judge by this.
WORKER_SILENT_AFTER = datetime.timedelta(minutes=10)
# the key columns a ledger made before supersedes and withdraws lacks
KEY_COLUMNS = ("supersedes", "withdraws")
OLD_LEDGER = ("The signature ledger was made before supersedes and withdraws "
              "were kept: it must be migrated before anything is signed.")
UNWRITABLE = "The signature ledger cannot be written: ask a Manager"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signatures (
    seq INTEGER PRIMARY KEY,
    prev TEXT NOT NULL,
    entry TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    signer TEXT NOT NULL,
    meaning TEXT NOT NULL,
    supersedes TEXT NOT NULL DEFAULT '',
    withdraws TEXT NOT NULL DEFAULT '',
    seal TEXT,
    seal_cert TEXT,
    sealed_at TEXT,
    UNIQUE (kind, record_id, record_hash, signer, meaning, supersedes, withdraws)
);
CREATE TRIGGER IF NOT EXISTS signatures_no_delete
BEFORE DELETE ON signatures
BEGIN
    SELECT RAISE(ABORT, 'append-only');
END;
CREATE TRIGGER IF NOT EXISTS signatures_no_replace
BEFORE INSERT ON signatures
WHEN EXISTS (SELECT 1 FROM signatures WHERE seq = NEW.seq OR hash = NEW.hash
  OR (kind = NEW.kind AND record_id = NEW.record_id
      AND record_hash = NEW.record_hash AND signer = NEW.signer
      AND meaning = NEW.meaning AND supersedes = NEW.supersedes
      AND withdraws = NEW.withdraws))
BEGIN
    SELECT RAISE(ABORT, 'append-only');
END;
CREATE TRIGGER IF NOT EXISTS signatures_seal_once
BEFORE UPDATE ON signatures
WHEN OLD.seq IS NOT NEW.seq OR OLD.prev IS NOT NEW.prev
  OR OLD.entry IS NOT NEW.entry OR OLD.hash IS NOT NEW.hash
  OR OLD.kind IS NOT NEW.kind OR OLD.record_id IS NOT NEW.record_id
  OR OLD.record_hash IS NOT NEW.record_hash OR OLD.signer IS NOT NEW.signer
  OR OLD.meaning IS NOT NEW.meaning OR OLD.supersedes IS NOT NEW.supersedes
  OR OLD.withdraws IS NOT NEW.withdraws OR OLD.seal IS NOT NULL
  OR OLD.seal_cert IS NOT NULL OR OLD.sealed_at IS NOT NULL
  OR NEW.seal IS NULL
BEGIN
    SELECT RAISE(ABORT, 'append-only');
END;
"""

_COLS = ("seq, prev, entry, hash, kind, record_id, record_hash, signer, "
         "meaning, supersedes, withdraws, seal, seal_cert, sealed_at")
COLUMNS = _COLS
_FIND = ("SELECT seq, hash FROM signatures WHERE kind=? AND record_id=? "
         "AND record_hash=? AND signer=? AND meaning=? AND supersedes=? "
         "AND withdraws=?")


try:
    _TEXT = basestring  # noqa: F821  (Python 2)
    _INT = (int, long)  # noqa: F821
except NameError:
    _TEXT = str
    _INT = (int,)


class LedgerError(Exception):
    """The ledger refused the request."""


def _connect(path=None):
    path = path or DB_PATH
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError:
            if not os.path.isdir(d):
                raise
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        # a table made before the key held supersedes and withdraws would
        # refuse every insert; say why rather than refuse each signature
        found = set(r[1] for r in conn.execute("PRAGMA table_info(signatures)"))
        if found and not found.issuperset(KEY_COLUMNS):
            raise LedgerError(OLD_LEDGER)
        conn.executescript(_SCHEMA)
    except BaseException:
        conn.close()
        raise
    return conn


def writable(path=None):
    """True when a row could be appended now: the ledger opens (made, with
    its folder, when missing), takes a write lock and writes its header
    back unchanged, all rolled back at once (a file SQLite may only read
    takes the lock but refuses the write). False on any SQLite error, a
    folder that cannot be made, or a ledger made before supersedes and
    withdraws."""
    try:
        conn = _connect(path)
    except (sqlite3.Error, OSError, LedgerError):
        return False
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.execute("PRAGMA user_version = %d" % int(version))
        finally:
            conn.execute("ROLLBACK")
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _row(r):
    try:
        entry = json.loads(r[2])
    except ValueError:
        entry = None
    return {
        "seq": r[0], "prev": r[1], "entry": entry, "hash": r[3],
        "seal": r[11], "seal_cert": r[12], "sealed_at": r[13],
    }


def _hash(prev, text):
    return canonical.sha256_bytes((prev + "\n" + text).encode("utf-8"))


def _keys(entry):
    """The seven key values of an entry: kind, record_id, record_hash,
    signer userid, meaning, supersedes and withdraws. The first five must be
    non-empty text, kind and meaning known ones; supersedes and withdraws
    are each a row number or null, kept as digits or ''. Anything else
    raises LedgerError."""
    try:
        keys = (entry["kind"], entry["record_id"], entry["record_hash"],
                entry["signer"]["userid"], entry["meaning"])
    except (KeyError, TypeError):
        raise LedgerError("The entry lacks kind, record_id, record_hash, "
                          "signer.userid or meaning.")
    for v in keys:
        if not isinstance(v, _TEXT) or not v:
            raise LedgerError("The entry's kind, record_id, record_hash, "
                              "signer.userid and meaning must be non-empty text.")
    if keys[0] not in KINDS:
        raise LedgerError("Unknown kind {0}.".format(keys[0]))
    if keys[4] not in MEANINGS:
        raise LedgerError("Unknown meaning {0}.".format(keys[4]))
    refs = []
    for name in ("supersedes", "withdraws"):
        ref = entry.get(name)
        if ref is not None and (isinstance(ref, bool) or not isinstance(ref, _INT)):
            raise LedgerError("The entry's {0} must be a row number or null.".format(name))
        refs.append("" if ref is None else "%d" % ref)
    return keys + tuple(refs)


def _last(conn):
    return conn.execute(
        "SELECT seq, hash FROM signatures ORDER BY seq DESC LIMIT 1").fetchone()


def _rollback(conn):
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def append(entry, path=None):
    """Chain entry onto the ledger. Returns {seq, hash, reused}; reused is
    True when the same signer already made this meaning on this record
    content (a row in the ledger or prepared in this transaction), and then
    nothing is written. Inside a transaction the row is prepared and written
    when the transaction commits (see the module's note)."""
    keys = _keys(entry)
    text = canonical.dumps(entry)
    txn = _transaction()
    try:
        if txn is None:
            return _append(keys, text, path)
        return _prepare(_manager(txn, path), keys, text)
    except sqlite3.Error:
        raise LedgerError("The signature could not be recorded.")


# ── the rows of the current transaction ─────────────────────────────────────

# before every other resource: the rows are committed before ZODB finishes,
# so a commit of the ledger that fails leaves nothing else committed
SORT_KEY = str(" senaite.pfas.signatures")
# the transaction's data slot holding {ledger path: its data manager}
_DATA = object()
RECORD_FAILED = "The signature could not be recorded."


def _transaction():
    """The current transaction, or None where there is no transaction
    package (the worker, the verifier): there a row is written at once."""
    try:
        import transaction
    except ImportError:
        return None
    return transaction.get()


def _conflict(message):
    """A ConflictError: the publisher retries the request."""
    try:
        from ZODB.POSException import ConflictError
    except ImportError:
        from transaction.interfaces import TransientError as ConflictError
    return ConflictError(message)


def _managers(txn, create):
    try:
        return txn.data(_DATA)
    except KeyError:
        if not create:
            return None
        found = {}
        txn.set_data(_DATA, found)
        return found


def _manager(txn, path):
    """This transaction's data manager for the ledger at path, joined."""
    path = path or DB_PATH
    found = _managers(txn, True)
    dm = found.get(path)
    if dm is None:
        dm = found[path] = _Pending(path)
    if not dm.joined:
        txn.join(dm)
        dm.joined = True
    return dm


def _pending_rows(path):
    """The rows the current transaction prepared on the ledger at path, as
    the reads return them; [] when there are none."""
    txn = _transaction()
    if txn is None:
        return []
    found = _managers(txn, False) or {}
    dm = found.get(path or DB_PATH)
    if dm is None:
        return []
    return [_row((r["seq"], r["prev"], r["text"], r["hash"]) + r["keys"] + (None, None, None))
            for r in dm.rows]


def _prepare(dm, keys, text):
    """Prepare one row in this transaction: a replay of a row in the ledger
    or of one already prepared returns that row; otherwise the row is
    chained onto the last prepared row, or onto the ledger's head."""
    for r in dm.rows:
        if r["keys"] == keys:
            return {"seq": r["seq"], "hash": r["hash"], "reused": True}
    conn = _connect(dm.path)
    try:
        found = conn.execute(_FIND, keys).fetchone()
        last = _last(conn)
    finally:
        conn.close()
    if found:
        return {"seq": found[0], "hash": found[1], "reused": True}
    head = (last[0], last[1]) if last else (0, GENESIS)
    if dm.rows:
        if head != dm.base:
            raise _conflict("The signature ledger moved under this transaction.")
        seq, prev = dm.rows[-1]["seq"], dm.rows[-1]["hash"]
    else:
        dm.base = head
        seq, prev = head
    h = _hash(prev, text)
    dm.rows.append({"seq": seq + 1, "prev": prev, "text": text, "hash": h, "keys": keys})
    return {"seq": seq + 1, "hash": h, "reused": False}


class _Savepoint(object):
    """Rolling back drops the rows prepared after it."""

    def __init__(self, dm):
        self.dm = dm
        self.count = len(dm.rows)

    def rollback(self):
        del self.dm.rows[self.count:]


class _Pending(object):
    """The data manager of one ledger file in one transaction: its prepared
    rows, inserted at the vote and committed at the finish."""

    transaction_manager = None

    def __init__(self, path):
        self.path = path
        self.rows = []
        # the ledger's (seq, hash) the first row was chained onto
        self.base = None
        self.conn = None
        self.joined = False

    def sortKey(self):
        return SORT_KEY

    def _drop(self):
        self.rows = []
        self.base = None
        self.joined = False

    def _close(self, rollback):
        conn, self.conn = self.conn, None
        if conn is not None:
            if rollback:
                _rollback(conn)
            conn.close()

    def abort(self, txn):
        # the transaction's abort, or a savepoint made before the first row
        # rolled back (the transaction then forgets this manager)
        self._close(True)
        self._drop()

    def tpc_begin(self, txn):
        pass

    def commit(self, txn):
        pass

    def tpc_vote(self, txn):
        if not self.rows:
            return
        conn = _connect(self.path)
        try:
            # readers wait until the finish: the commit there takes no lock
            conn.execute("BEGIN EXCLUSIVE")
            try:
                last = _last(conn)
                if ((last[0], last[1]) if last else (0, GENESIS)) != self.base:
                    raise _conflict("The signature ledger moved under this transaction.")
                for r in self.rows:
                    conn.execute(
                        "INSERT INTO signatures (seq, prev, entry, hash, kind, record_id, "
                        "record_hash, signer, meaning, supersedes, withdraws) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r["seq"], r["prev"], r["text"], r["hash"]) + r["keys"])
            except BaseException:
                _rollback(conn)
                raise
        except sqlite3.Error:
            conn.close()
            raise LedgerError(RECORD_FAILED)
        except BaseException:
            conn.close()
            raise
        self.conn = conn

    def tpc_finish(self, txn):
        conn, self.conn = self.conn, None
        try:
            if conn is not None:
                try:
                    conn.execute("COMMIT")
                except sqlite3.Error:
                    _rollback(conn)
                    raise LedgerError(RECORD_FAILED)
        finally:
            if conn is not None:
                conn.close()
            self._drop()

    def tpc_abort(self, txn):
        self._close(True)
        self._drop()

    def savepoint(self):
        return _Savepoint(self)


def _append(keys, text, path):
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            found = conn.execute(_FIND, keys).fetchone()
            if found:
                conn.execute("COMMIT")
                return {"seq": found[0], "hash": found[1], "reused": True}
            last = _last(conn)
            prev = last[1] if last else GENESIS
            h = _hash(prev, text)
            cur = conn.execute(
                "INSERT INTO signatures (prev, entry, hash, kind, record_id, "
                "record_hash, signer, meaning, supersedes, withdraws) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (prev, text, h) + keys)
            seq = cur.lastrowid
            conn.execute("COMMIT")
            return {"seq": seq, "hash": h, "reused": False}
        except sqlite3.IntegrityError:
            _rollback(conn)
            found = conn.execute(_FIND, keys).fetchone()
            if found:
                return {"seq": found[0], "hash": found[1], "reused": True}
            raise
        except BaseException:
            _rollback(conn)
            raise
    finally:
        conn.close()


def rows(path=None, kind=None, record_id=None, signer=None, meaning=None,
         since=None, unsealed=False):
    """The rows in seq order, each with its entry parsed, the rows this
    transaction prepared last. since is an ISO UTC string compared with the
    entry's signed_at; unsealed keeps rows with no seal."""
    where, args = [], []
    wanted = []
    for col, val in (("kind", kind), ("record_id", record_id),
                     ("signer", signer), ("meaning", meaning)):
        if val is not None:
            where.append(col + "=?")
            args.append(val)
            wanted.append((col, val))
    if unsealed:
        where.append("seal IS NULL")
    sql = "SELECT " + _COLS + " FROM signatures"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq"
    try:
        conn = _connect(path)
        try:
            out = [_row(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        # a reader says the ledger could not be read, never that it is empty
        raise LedgerError("The signatures could not be read.")
    for r in _pending_rows(path):
        if all(_column(r, col) == val for col, val in wanted):
            out.append(r)
    if since is not None:
        out = [r for r in out if _signed_at(r) >= since]
    return out


def _column(r, col):
    """A prepared row's key column, read from its entry."""
    e = r.get("entry") or {}
    if col == "signer":
        return (e.get("signer") or {}).get("userid")
    return e.get(col)


def _signed_at(r):
    """The row's signed_at as text; "" when its entry is not an object or
    the time is not text (a row written around the ledger)."""
    e = r.get("entry")
    at = e.get("signed_at") if isinstance(e, dict) else None
    return at if isinstance(at, _TEXT) else ""


def for_record(kind, record_id, path=None):
    """Every row on one record, in seq order."""
    return rows(path=path, kind=kind, record_id=record_id)


def row(seq, path=None):
    """The one row numbered seq, with its entry parsed (a row this
    transaction prepared too); None when there is none."""
    try:
        conn = _connect(path)
        try:
            r = conn.execute("SELECT " + _COLS + " FROM signatures WHERE seq=?",
                             (seq,)).fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        raise LedgerError("The signatures could not be read.")
    if r:
        return _row(r)
    for p in _pending_rows(path):
        if p["seq"] == seq:
            return p
    return None


def head(path=None):
    """(seq, hash) of the last row, a row this transaction prepared
    included; (0, GENESIS) when the ledger is empty."""
    pending = _pending_rows(path)
    if pending:
        return (pending[-1]["seq"], pending[-1]["hash"])
    conn = _connect(path)
    try:
        r = _last(conn)
    finally:
        conn.close()
    return (r[0], r[1]) if r else (0, GENESIS)


def verify_chain(path=None):
    """None when the chain is whole, else the seq of the first broken link:
    a wrong prev, a hash that is not of prev and entry, or key columns
    (supersedes and withdraws among them) that differ from the entry."""
    return check(path)[0]


def check(path=None):
    """(the seq of the first broken link or None, the seq of the last row
    read whole): the chain as far as it was read, so a row appended while it
    is read is never reported as checked. The committed rows only: a row
    this transaction prepared is not yet in the chain."""
    conn = _connect(path)
    try:
        data = conn.execute(
            "SELECT " + _COLS + " FROM signatures ORDER BY seq").fetchall()
    finally:
        conn.close()
    return check_rows(data)


def check_rows(data):
    """check over rows already read, as tuples in COLUMNS order by seq: a
    reader that opens the file its own way (the verifier, read-only) checks
    the chain by this same rule. A prev, entry or hash that is not text (a
    row written around the ledger) is a break, never an error."""
    prev, whole = GENESIS, 0
    for r in data:
        if not all(isinstance(v, _TEXT) for v in r[1:4]):
            return r[0], whole
        if r[1] != prev or r[3] != _hash(r[1], r[2]):
            return r[0], whole
        try:
            e = json.loads(r[2])
            cols = _keys(e)
        except (ValueError, LedgerError):
            return r[0], whole
        if cols != tuple(r[4:11]) or canonical.dumps(e) != r[2]:
            return r[0], whole
        prev, whole = r[3], r[0]
    return None, whole


def set_seal(seq, seal_b64, cert_fp, sealed_at, path=None):
    """Fill the seal columns of one row, once. A second call raises."""
    for v in (seal_b64, cert_fp, sealed_at):
        if not isinstance(v, _TEXT) or not v:
            raise LedgerError("The seal, its certificate and its time are required.")
    try:
        _set_seal(seq, seal_b64, cert_fp, sealed_at, path)
    except sqlite3.Error:
        raise LedgerError("The seal could not be recorded.")


def _set_seal(seq, seal_b64, cert_fp, sealed_at, path):
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            r = conn.execute(
                "SELECT seal, seal_cert, sealed_at FROM signatures WHERE seq=?", (seq,)).fetchone()
            if r is None:
                raise LedgerError("No signature row {0}.".format(seq))
            if r[0] is not None or r[1] is not None or r[2] is not None:
                raise LedgerError(
                    "Signature row {0} is already sealed.".format(seq))
            conn.execute(
                "UPDATE signatures SET seal=?, seal_cert=?, sealed_at=? "
                "WHERE seq=?", (seal_b64, cert_fp, sealed_at, seq))
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise
    finally:
        conn.close()
