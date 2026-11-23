# -*- coding: utf-8 -*-
"""What a person types to sign: their password, or the PIN they chose.

Every signature asks for it again. A person may set a PIN on their own
profile and make it their default for signing; the password stays their
sign-in. Only a salted hash of a PIN is kept (PBKDF2-HMAC-SHA256), never the
PIN, and no PIN or password is ever logged. Failed attempts are counted per
person: after the rules' lock_tries failures within lock_minutes, signing is
refused for that person until lock_minutes have passed since the last
failure; every failure, every lock and every PIN change is recorded as an
event (events()), never with the secret. The rules (signing_rules: PIN
length, lock, expiry) are passed in; without them the seeds apply.

When each person's password was last set is kept too (password_changed,
from the user folder's own event), so a password and a PIN expire on one
schedule. A reset mailed by a manager, or a password set by another
signed-in account, opens a reset: the signatures made as its person until
they change the password themselves, signed in, are listed for review
(resets()).

Stored in SQLite (PFAS_CREDENTIALS_DB, /data/qc/sign_credentials.db), not
the ZODB: a refused signature aborts its transaction, and the failure must
still count.

    pin_problem(pin, rules)          -> "" | why the PIN is refused
    hash_pin(pin, salt=None)         -> the stored form
    pin_matches(pin, stored)         -> bool, in constant time
    set_pin(userid, pin, at, rules)  the PIN set (and its default kept)
    remove_pin(userid, at)           the PIN gone, the password the default
    set_default(userid, use_pin, at) which one signing asks for
    method(userid)                   -> "pin" | "password"
    has_pin(userid)                  -> bool
    check_pin(userid, pin)           -> bool
    failure(userid, kind, now, at, rules), locked(userid, now, rules) -> seconds left,
    clear(userid), events(limit), attempts(limit)
    pin_expired(userid, now, rules), password_expired(userid, now, rules)
    password_seen(userid, at), password_changed(userid, at, by)
    reset_sent(userid, at, by), resets(userid=None), open_reset(userid)

Pure apart from SQLite; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import binascii
import datetime
import hashlib
import hmac
import math
import os
import sqlite3

from senaite.pfas import signing_rules

DB_PATH = os.environ.get("PFAS_CREDENTIALS_DB", "/data/qc/sign_credentials.db")

PASSWORD, PIN = "password", "pin"
# the seeds of the rules (signing_rules.SEEDS): a PIN is digits only, at
# least PIN_MIN and at most PIN_MAX of them; LOCK_FAILURES failed signing
# attempts within LOCK_WINDOW seconds lock signing for LOCK_WINDOW seconds
PIN_MIN, PIN_MAX = signing_rules.SEEDS["pin_min"], signing_rules.SEEDS["pin_max"]
ITERATIONS = 100000
LOCK_FAILURES = signing_rules.SEEDS["lock_tries"]
LOCK_WINDOW = signing_rules.lock_seconds(signing_rules.SEEDS)
STAMP = "%Y-%m-%dT%H:%M:%SZ"

PIN_FORMAT_TEXT = "A PIN is %d to %d digits."
PIN_FORMAT = PIN_FORMAT_TEXT % (PIN_MIN, PIN_MAX)
PIN_SIMPLE = "Choose a PIN that is not one digit repeated or a run of digits."
# the events a Signing attempts table shows: a wrong secret and a lock
ATTEMPT_ACTIONS = ("failed", "locked")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pins (
    userid TEXT PRIMARY KEY, pin_hash TEXT, use_pin INTEGER, set_at TEXT);
CREATE TABLE IF NOT EXISTS failures (userid TEXT, at REAL, kind TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, userid TEXT, action TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS passwords (userid TEXT PRIMARY KEY, set_at TEXT);
CREATE TABLE IF NOT EXISTS resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, userid TEXT, at TEXT, by TEXT, closed_at TEXT);
"""


def _rules(rules):
    return rules if rules is not None else signing_rules.settings(None)


def pin_format(rules=None):
    rules = _rules(rules)
    return PIN_FORMAT_TEXT % (rules["pin_min"], rules["pin_max"])


def parse_stamp(text):
    """A stored stamp (STAMP, UTC) as a naive datetime; None when unreadable."""
    try:
        return datetime.datetime.strptime(("%s" % (text or ""))[:20], STAMP)
    except ValueError:
        return None


def expired(set_at, now, rules=None):
    """True when a credential set at `set_at` (a stored stamp) has passed
    the rules' expiry_days at `now` (a naive UTC datetime). No expiry set,
    never; a set time that cannot be read counts as expired."""
    days = _rules(rules).get("expiry_days")
    if not days:
        return False
    when = parse_stamp(set_at)
    return when is None or now - when >= datetime.timedelta(days=int(days))


def _connect(path=None):
    path = path or DB_PATH
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _d(row):
    """A fetched row as a dict. Under Python 2 a sqlite3.Row refuses a unicode
    column name, and this module has unicode_literals: a row read by name is
    read through this."""
    return dict(row) if row is not None else None


def _b(text):
    return text if isinstance(text, bytes) else ("%s" % (text or "")).encode("utf-8")


def _runs(pin):
    steps = set(int(b) - int(a) for a, b in zip(pin, pin[1:]))
    return len(steps) == 1 and steps <= set((-1, 0, 1))


def pin_problem(pin, rules=None):
    """"" when the PIN may be set, else why not: digits only, the rules'
    pin_min to pin_max of them, not one digit repeated or a run (123456)."""
    rules = _rules(rules)
    pin = "%s" % (pin or "")
    if not pin.isdigit() or not rules["pin_min"] <= len(pin) <= rules["pin_max"]:
        return pin_format(rules)
    if _runs(pin):
        return PIN_SIMPLE
    return ""


def hash_pin(pin, salt=None, iterations=ITERATIONS):
    """"pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>"; a new random
    salt unless one is given."""
    salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", _b(pin), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, binascii.hexlify(salt).decode("ascii"),
                                       binascii.hexlify(digest).decode("ascii"))


def pin_matches(pin, stored):
    """True when the PIN hashes to the stored form, compared in constant
    time; False for anything malformed."""
    try:
        algo, iterations, salt, want = ("%s" % stored).split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hash_pin(pin, binascii.unhexlify(salt), int(iterations)).split("$")[3]
    except (TypeError, ValueError, binascii.Error):
        return False
    return hmac.compare_digest(_b(got), _b(want))


def _event(con, at, userid, action, kind=""):
    con.execute("INSERT INTO events (at, userid, action, kind) VALUES (?,?,?,?)",
                ("%s" % at, userid, action, kind))


def set_pin(userid, pin, at, path=None, rules=None):
    """Keep the PIN's hash for `userid` (the PIN itself never); raises
    ValueError with pin_problem's reason. A first PIN becomes the default."""
    why = pin_problem(pin, rules)
    if why:
        raise ValueError(why)
    con = _connect(path)
    try:
        with con:
            row = _d(con.execute("SELECT use_pin FROM pins WHERE userid=?", (userid,)).fetchone())
            use = 1 if row is None else row["use_pin"]
            con.execute("INSERT OR REPLACE INTO pins (userid, pin_hash, use_pin, set_at) VALUES (?,?,?,?)",
                        (userid, hash_pin(pin), use, "%s" % at))
            _event(con, at, userid, "pin changed" if row is not None else "pin set")
    finally:
        con.close()


def remove_pin(userid, at, path=None):
    con = _connect(path)
    try:
        with con:
            if con.execute("DELETE FROM pins WHERE userid=?", (userid,)).rowcount:
                _event(con, at, userid, "pin removed")
    finally:
        con.close()


def set_default(userid, use_pin, at, path=None):
    """Which one signing asks `userid` for; a PIN only once one is set.
    Returns the method now in force."""
    con = _connect(path)
    try:
        with con:
            if con.execute("UPDATE pins SET use_pin=? WHERE userid=?",
                           (1 if use_pin else 0, userid)).rowcount:
                _event(con, at, userid, "signs with %s" % (PIN if use_pin else PASSWORD))
    finally:
        con.close()
    return method(userid, path=path)


def _pin_row(userid, path=None):
    con = _connect(path)
    try:
        return _d(con.execute("SELECT pin_hash, use_pin, set_at FROM pins WHERE userid=?",
                              (userid,)).fetchone())
    finally:
        con.close()


def has_pin(userid, path=None):
    return _pin_row(userid, path) is not None


def method(userid, path=None):
    """PIN when `userid` has set one and made it their default, else
    PASSWORD."""
    row = _pin_row(userid, path)
    return PIN if row is not None and row["use_pin"] else PASSWORD


def check_pin(userid, pin, path=None):
    row = _pin_row(userid, path)
    return row is not None and pin_matches(pin, row["pin_hash"])


def pin_expired(userid, now, rules=None, path=None):
    """True when `userid`'s PIN has passed the rules' expiry at `now` (a
    naive UTC datetime); False with no PIN or no expiry."""
    row = _pin_row(userid, path)
    return row is not None and expired(row["set_at"], now, rules)


def failure(userid, kind, now, at, path=None, rules=None):
    """Count a failed signing attempt (`now`, seconds since the epoch; `at`,
    the stamp the event records) and record it; the failure that reaches the
    rules' lock_tries records the lock too."""
    rules = _rules(rules)
    con = _connect(path)
    try:
        with con:
            con.execute("INSERT INTO failures (userid, at, kind) VALUES (?,?,?)", (userid, now, kind))
            _event(con, at, userid, "failed", kind)
            n = con.execute("SELECT COUNT(*) FROM failures WHERE userid=? AND at>?",
                            (userid, now - signing_rules.lock_seconds(rules))).fetchone()[0]
            if n == rules["lock_tries"]:
                _event(con, at, userid, "locked", kind)
    finally:
        con.close()


def locked(userid, now, path=None, rules=None):
    """Seconds until `userid` may sign again; 0 when not locked."""
    rules = _rules(rules)
    window = signing_rules.lock_seconds(rules)
    con = _connect(path)
    try:
        rows = [r[0] for r in con.execute(
            "SELECT at FROM failures WHERE userid=? AND at>? ORDER BY at",
            (userid, now - window)).fetchall()]
    finally:
        con.close()
    if len(rows) < rules["lock_tries"]:
        return 0
    return max(0, int(math.ceil(rows[-1] + window - now)))


def clear(userid, path=None):
    """A confirmed signature clears the person's failures."""
    con = _connect(path)
    try:
        with con:
            con.execute("DELETE FROM failures WHERE userid=?", (userid,))
    finally:
        con.close()


def events(limit=200, path=None):
    """The newest events first: [{"at", "userid", "action", "kind"}]."""
    con = _connect(path)
    try:
        return [dict(r) for r in con.execute(
            "SELECT at, userid, action, kind FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        con.close()


def attempts(limit=100, path=None):
    """The failed signing attempts and the locks they made, newest first:
    [{"at", "userid", "action", "kind"}]."""
    marks = ",".join("?" * len(ATTEMPT_ACTIONS))
    con = _connect(path)
    try:
        return [dict(r) for r in con.execute(
            "SELECT at, userid, action, kind FROM events WHERE action IN (%s) "
            "ORDER BY id DESC LIMIT ?" % marks, tuple(ATTEMPT_ACTIONS) + (limit,)).fetchall()]
    finally:
        con.close()


# ── passwords: when each was set, and the resets ─────────────────────────────

def password_set_at(userid, path=None):
    """The stamp `userid`'s password was last set, or None when never seen."""
    con = _connect(path)
    try:
        row = _d(con.execute("SELECT set_at FROM passwords WHERE userid=?", (userid,)).fetchone())
    finally:
        con.close()
    return row["set_at"] if row is not None else None


def password_seen(userid, at, path=None):
    """An account whose password was never seen set counts from `at`, the
    first time it is seen in use: nobody is expired by the rule's arrival."""
    con = _connect(path)
    try:
        with con:
            con.execute("INSERT OR IGNORE INTO passwords (userid, set_at) VALUES (?,?)",
                        (userid, "%s" % at))
    finally:
        con.close()


def password_expired(userid, now, rules=None, path=None):
    """True when `userid`'s password, set when password_set_at says, has
    passed the rules' expiry at `now`; never seen set, it has not."""
    set_at = password_set_at(userid, path)
    return set_at is not None and expired(set_at, now, rules)


def _open_reset(con, userid, at, by):
    con.execute("INSERT INTO resets (userid, at, by, closed_at) VALUES (?,?,?,NULL)",
                (userid, "%s" % at, by))


def _drop_pin(con, at, userid, by):
    """Another hand set the password, so the person's PIN goes: they sign
    with the password until they set a new PIN on My profile."""
    if con.execute("DELETE FROM pins WHERE userid=?", (userid,)).rowcount:
        _event(con, at, userid, "pin removed", by)


def password_changed(userid, at, by, path=None, review=True):
    """`userid`'s password was set at `at` by the signed-in account `by`
    ("" when nobody was signed in: the reset link). Set by another account,
    it opens a reset; set by its holder signed in, it closes every open one.
    Set through the reset link it closes none: whoever held the link may not
    be the person. A password set by another account, or through the link,
    also removes the person's PIN (a new one is set on My profile). review False (a service account, which signs nothing)
    keeps the time alone. Returns "reset", "changed" or "link"."""
    con = _connect(path)
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO passwords (userid, set_at) VALUES (?,?)",
                        (userid, "%s" % at))
            if not review:
                _event(con, at, userid, "password changed")
                return "changed"
            if by and by != userid:
                _open_reset(con, userid, at, by)
                _event(con, at, userid, "password set by another", by)
                _drop_pin(con, at, userid, by)
                return "reset"
            if not by:
                _event(con, at, userid, "password set by reset link")
                _drop_pin(con, at, userid, "")
                return "link"
            con.execute("UPDATE resets SET closed_at=? WHERE userid=? AND closed_at IS NULL",
                        ("%s" % at, userid))
            _event(con, at, userid, "password changed")
            return "changed"
    finally:
        con.close()


def reset_sent(userid, at, by, path=None):
    """A manager mailed `userid` a reset link: recorded (never the link), and
    a reset opens, as whoever holds the link may set the password. A
    person's own reset opens none."""
    con = _connect(path)
    try:
        with con:
            _event(con, at, userid, "reset e-mail sent", by)
            if by and by != userid:
                _open_reset(con, userid, at, by)
    finally:
        con.close()


def resets(userid=None, limit=200, path=None):
    """The resets, newest first: [{"id", "userid", "at", "by", "closed_at"}],
    closed_at None while the holder has not changed the password."""
    con = _connect(path)
    try:
        if userid:
            rows = con.execute("SELECT id, userid, at, by, closed_at FROM resets WHERE userid=? "
                               "ORDER BY id DESC LIMIT ?", (userid, limit))
        else:
            rows = con.execute("SELECT id, userid, at, by, closed_at FROM resets "
                               "ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows.fetchall()]
    finally:
        con.close()


def open_reset(userid, path=None):
    """The newest reset of `userid` still open, or None."""
    for r in resets(userid, path=path):
        if not r["closed_at"]:
            return r
    return None
