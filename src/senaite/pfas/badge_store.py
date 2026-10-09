# -*- coding: utf-8 -*-
"""Badges and registered lab terminals (part C).

The rules: a badge alone signs a person in, but only at a
REGISTERED lab terminal, never for a Manager / site-admin account; a scan
switches user; terminals sign out after 10 minutes idle.

Stored in SQLite (/data/qc/badges.db), not the ZODB: every failed scan is a
write, and the ZODB would turn a stream of them into conflicts and growth.

    issue(userid, by, when) -> the badge CODE, returned once and never stored:
                               only sha256(code) is kept; a new badge revokes
                               the previous one
    revoke(userid, by, when), status(userid), user_for_code(code)
    register_terminal(name, by, when) -> the terminal TOKEN (kept in that
                               browser's cookie; only its hash is stored)
    terminal_for_token(token), revoke_terminal(id, by, when), terminals()
    failure(terminal_id, now), locked(terminal_id, now), clear(terminal_id)
    log_signin(...), signins(), events()

Codes: 160 random bits (os.urandom), base32 -- 32 characters, fits a Code 128
or QR on a badge. Pure apart from SQLite; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import base64
import hashlib
import os
import sqlite3

DB_PATH = os.environ.get("PFAS_BADGE_DB", "/data/qc/badges.db")
LOCK_FAILURES = 5          # failed scans at one terminal ...
LOCK_WINDOW = 300          # ... within 5 minutes lock it for LOCK_WINDOW seconds

_SCHEMA = """
CREATE TABLE IF NOT EXISTS badges (
    userid TEXT PRIMARY KEY, code_hash TEXT UNIQUE, issued_at TEXT, issued_by TEXT);
CREATE TABLE IF NOT EXISTS badge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, userid TEXT, action TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS terminals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, token_hash TEXT UNIQUE,
    registered_at TEXT, registered_by TEXT, revoked_at TEXT, revoked_by TEXT);
CREATE TABLE IF NOT EXISTS failures (terminal_id INTEGER, at REAL);
CREATE TABLE IF NOT EXISTS activity (
    terminal_id INTEGER, userid TEXT, last_seen REAL, PRIMARY KEY (terminal_id, userid));
CREATE TABLE IF NOT EXISTS signins (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, userid TEXT, terminal_id INTEGER,
    ok INTEGER, reason TEXT);
CREATE TABLE IF NOT EXISTS tile_hidden (
    terminal_id INTEGER, userid TEXT, at TEXT, by TEXT, PRIMARY KEY (terminal_id, userid));
"""


def connect(path=None):
    path = path or DB_PATH
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _hash(secret):
    if not isinstance(secret, bytes):
        secret = secret.encode("utf-8")
    return hashlib.sha256(secret).hexdigest()


def normalise(code):
    """What a scanner or a person typed, as the code: upper case, no spaces
    or dashes (a badge may print it in groups)."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def new_code():
    raw = base64.b32encode(os.urandom(20))
    if not isinstance(raw, type("")):
        raw = raw.decode("ascii")
    return raw.rstrip("=")


def new_token():
    raw = base64.b16encode(os.urandom(32))
    if not isinstance(raw, type("")):
        raw = raw.decode("ascii")
    return raw.lower()


# ── badges ─────────────────────────────────────────────────────────────────

def issue(con, userid, by, when):
    code = new_code()
    with con:
        replaced = con.execute("SELECT 1 FROM badges WHERE userid=?", (userid,)).fetchone()
        con.execute("DELETE FROM badges WHERE userid=?", (userid,))
        con.execute("INSERT INTO badges (userid, code_hash, issued_at, issued_by) VALUES (?,?,?,?)",
                    (userid, _hash(normalise(code)), when, by))
        con.execute("INSERT INTO badge_events (at, userid, action, by) VALUES (?,?,?,?)",
                    (when, userid, "replaced" if replaced else "issued", by))
    return code


def revoke(con, userid, by, when):
    with con:
        n = con.execute("DELETE FROM badges WHERE userid=?", (userid,)).rowcount
        if n:
            con.execute("INSERT INTO badge_events (at, userid, action, by) VALUES (?,?,?,?)",
                        (when, userid, "revoked", by))
    return bool(n)


def status(con, userid):
    row = con.execute("SELECT issued_at, issued_by FROM badges WHERE userid=?", (userid,)).fetchone()
    # positional: under Python 2 a sqlite3.Row refuses unicode column names
    # (unicode_literals), which made every lookup of a real badge fail
    return {"active": row is not None, "issued_at": row[0] if row else "",
            "issued_by": row[1] if row else ""}


def user_for_code(con, code):
    code = normalise(code)
    row = con.execute("SELECT userid FROM badges WHERE code_hash=?", (_hash(code),)).fetchone()
    return row[0] if row else None


def events(con, userid=None, limit=200):
    if userid:
        rows = con.execute("SELECT * FROM badge_events WHERE userid=? ORDER BY id DESC LIMIT ?",
                           (userid, limit))
    else:
        rows = con.execute("SELECT * FROM badge_events ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# ── terminals ──────────────────────────────────────────────────────────────

def register_terminal(con, name, by, when):
    token = new_token()
    with con:
        con.execute("INSERT INTO terminals (name, token_hash, registered_at, registered_by) "
                    "VALUES (?,?,?,?)", (name, _hash(token), when, by))
    return token


def terminal_for_token(con, token):
    if not token or len(token) < 32:
        return None
    row = con.execute("SELECT id, name FROM terminals WHERE token_hash=? AND revoked_at IS NULL",
                      (_hash(token),)).fetchone()
    return dict(row) if row else None


def revoke_terminal(con, terminal_id, by, when):
    with con:
        return bool(con.execute("UPDATE terminals SET revoked_at=?, revoked_by=? "
                                "WHERE id=? AND revoked_at IS NULL", (when, by, terminal_id)).rowcount)


def terminals(con):
    return [dict(r) for r in con.execute(
        "SELECT id, name, registered_at, registered_by, revoked_at, revoked_by FROM terminals ORDER BY id")]


# ── failed scans, lockout, sign-in log ─────────────────────────────────────

def failure(con, terminal_id, now):
    with con:
        con.execute("INSERT INTO failures (terminal_id, at) VALUES (?,?)", (terminal_id, now))
        con.execute("DELETE FROM failures WHERE at < ?", (now - 24 * 3600,))


def locked(con, terminal_id, now):
    n = con.execute("SELECT COUNT(*) FROM failures WHERE terminal_id=? AND at >= ?",
                    (terminal_id, now - LOCK_WINDOW)).fetchone()[0]
    return n >= LOCK_FAILURES


def clear(con, terminal_id):
    with con:
        con.execute("DELETE FROM failures WHERE terminal_id=?", (terminal_id,))


# ── idle sign-out, enforced by the server ──────────────────────────────────
# The page's 10-minute timer only runs while a page is open; a reopened
# browser or a request that never draws a page would otherwise inherit the
# previous person's session (plone.session's timeout is 0 here).

TOUCH_EVERY = 30           # seconds between activity writes for one person


def last_seen(con, terminal_id, userid):
    row = con.execute("SELECT last_seen FROM activity WHERE terminal_id=? AND userid=?",
                      (terminal_id, userid)).fetchone()
    return row[0] if row else None


def touch(con, terminal_id, userid, now):
    with con:
        con.execute("INSERT OR REPLACE INTO activity (terminal_id, userid, last_seen) VALUES (?,?,?)",
                    (terminal_id, userid, now))


def idle_verdict(last, now, limit):
    """"expired" (sign out), "touch" (record activity) or "fresh" (nothing to
    do) for a signed-in person at a terminal. No record yet = activity starts
    now (a password sign-in at the terminal)."""
    if last is None:
        return "touch"
    if now - last > limit:
        return "expired"
    return "touch" if now - last >= TOUCH_EVERY else "fresh"


def log_signin(con, userid, terminal_id, ok, reason, when):
    with con:
        con.execute("INSERT INTO signins (at, userid, terminal_id, ok, reason) VALUES (?,?,?,?,?)",
                    (when, userid or "", terminal_id, 1 if ok else 0, reason or ""))


def signins(con, limit=100):
    return [dict(r) for r in con.execute(
        "SELECT s.*, t.name AS terminal FROM signins s LEFT JOIN terminals t ON t.id = s.terminal_id "
        "ORDER BY s.id DESC LIMIT ?", (limit,))]


# ── sign-in page tiles ──────────────────────────────────────────
# The accounts that signed in successfully AT THIS TERMINAL (badge or
# password) within the last TILE_DAYS, newest first, at most TILE_MAX; a
# manager can hide one ("Forget") until that person signs in there again.
# The sign-in log itself is never edited.

TILE_DAYS = 30
TILE_MAX = 12


def terminal_accounts(con, terminal_id, since):
    """[userid] newest first: successful sign-ins at the terminal since the
    ISO time `since`, minus those hidden after their last sign-in."""
    rows = con.execute(
        "SELECT s.userid, MAX(s.at) AS last FROM signins s "
        "WHERE s.terminal_id=? AND s.ok=1 AND s.userid<>'' AND s.at>=? "
        "GROUP BY s.userid ORDER BY last DESC", (terminal_id, since)).fetchall()
    hidden = dict(con.execute("SELECT userid, at FROM tile_hidden WHERE terminal_id=?",
                              (terminal_id,)).fetchall())
    return [r[0] for r in rows if not (r[0] in hidden and hidden[r[0]] >= r[1])]


def hide_tile(con, terminal_id, userid, by, when):
    with con:
        con.execute("INSERT OR REPLACE INTO tile_hidden (terminal_id, userid, at, by) VALUES (?,?,?,?)",
                    (terminal_id, userid, when, by))
