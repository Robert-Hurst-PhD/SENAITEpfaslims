# -*- coding: utf-8 -*-
"""Change history for laboratory configuration.

Every save of a configuration store records ONE entry per (store, key) per
transaction: who, when, and the path-level changes with the value before and
after. ISO 17025 §8.3 expects that record for acceptance criteria.

HOW A STORE TAKES PART
    config_history.track(portal, "method_profile", method_id, getter)
is called by the store's save function BEFORE it writes. The first call for a
(store, key) in a transaction captures the "before" value through `getter`
(which reads the stored value). A before-commit hook then reads the final
value through the same getter, diffs, and writes one entry. So:
  * a request that saves the same key twice records one entry;
  * a Zope conflict retry re-runs the whole request: no duplicate entry;
  * an aborted save leaves no entry;
  * a save that changes nothing records nothing.

STORAGE
The table config_history of the shared results database (PFAS_QC_DB,
config_history_db), one row per entry, keyed "<ISO timestamp>-<uuid>" so
concurrent saves never contend on a counter; each row holds the JSON entry.
An entry commits or rolls back WITH the change it describes: the entries of a
transaction wait in a data manager that joins it and writes them when the
transaction votes, last of its resources, so a save that aborts or meets a
conflict writes no row, and a strict store's save fails when its row cannot
be written. The entries kept on the portal before the move (HISTORY_KEY)
stay there; move_from_annotation copies them into the table and verifies
the copy; until the copy is verified both are read.

The diff, apply and conflict functions are pure (no Zope) and shared with
tools/config_save_audit.py. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import copy
import json
import logging
import os
import uuid
from datetime import datetime

logger = logging.getLogger("senaite.pfas.config_history")

# the entries kept on the portal before the move to the results database
HISTORY_KEY = "senaite.pfas.config_history"
# set once every entry of HISTORY_KEY is verified in the table:
# {"at", "count", "checksum"}
MOVED_KEY = "senaite.pfas.config_history_moved"
# the results database; None reads PFAS_QC_DB
DB_PATH = None

# Keys nobody edits: timestamps, seeding markers and values the system derives.
# A change to one of these alone records nothing (they would bury real edits).
# The analyte panel is not among them: it follows the services' Method links,
# and a link made or broken is recorded ("Analyte links: +a, -b").
IGNORED_KEYS = frozenset(["updated_at", "_seeded", "matrix_uid_map",
                          "analyte_links_v", "display_analyte_set",
                          "method_id"])

# Keys counted in the version stamp but kept out of history entries. The
# surrogate map is owned by each method profile and recorded, and reverted,
# with it.
HISTORY_ONLY_IGNORED = frozenset()

# Stores whose save FAILS when its history entry cannot be written: the
# acceptance criteria, the instrument maps and the certificate wording.
# Elsewhere a missing entry is logged.
STRICT_STORES = frozenset(["method_profile", "import_profile", "qc_qualifiers",
                          "lab_identity", "person_roles", "lab_timezone",
                          "report_tiers"])


class HistoryNotRecorded(Exception):
    """A strict store's change could not be recorded; its save is refused."""


# Stores whose values are secrets: the entry says a change happened, not what.
REDACTED_STORES = frozenset(["facility_api_key"])

_EMPTY = (None, "", u"", [], {})
_MISSING = object()


# ── pure: diff / apply / conflicts ───────────────────────────────────────────

def _is_empty(v):
    return v is _MISSING or any(v == e and type(v) is type(e) for e in _EMPTY) or v is None


def diff(before, after, path=()):
    """[(path_tuple, before, after)] -- the smallest changed paths.

    Dicts recurse by key; lists of equal length recurse by index; lists of
    different length are one change at the list's path. Missing and empty
    (None, "", [], {}) are treated as the same (shape only, not a change).
    """
    out = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after), key=lambda x: "%s" % x):
            if not path and (k in IGNORED_KEYS or k in HISTORY_ONLY_IGNORED):
                continue
            if k in ("updated_at", "updated_by", "_seeded"):
                continue
            out += diff(before.get(k, _MISSING), after.get(k, _MISSING), path + (k,))
        return out
    if (isinstance(before, list) and isinstance(after, list)
            and len(before) == len(after)):
        for i, (b, a) in enumerate(zip(before, after)):
            out += diff(b, a, path + (i,))
        return out
    if before == after or (_is_empty(before) and _is_empty(after)):
        return out
    out.append((path, None if before is _MISSING else before,
                None if after is _MISSING else after))
    return out


def get_path(value, path):
    for p in path:
        if isinstance(value, dict):
            if p not in value:
                return _MISSING
            value = value[p]
        elif isinstance(value, list) and isinstance(p, int) and 0 <= p < len(value):
            value = value[p]
        else:
            return _MISSING
    return value


def set_path(value, path, new):
    """A copy of `value` with `path` set to `new` (None removes a dict key)."""
    root = copy.deepcopy(value)
    if not path:
        return copy.deepcopy(new)
    node = root
    for p in path[:-1]:
        if isinstance(node, dict):
            node = node.setdefault(p, {})
        else:
            node = node[p]
    last = path[-1]
    if isinstance(node, dict) and new is None:
        node.pop(last, None)
    else:
        node[last] = copy.deepcopy(new)
    return root


def revert_conflicts(current, changes):
    """Paths whose CURRENT value is no longer the entry's "after": a later
    change touched them, so reverting would silently undo that change too."""
    bad = []
    for ch in changes:
        path = tuple(ch["path"])
        cur = get_path(current, path)
        cur = None if cur is _MISSING else cur
        if cur != ch["after"] and not (_is_empty(cur) and _is_empty(ch["after"])):
            bad.append(path)
    return bad


def reverted(current, changes):
    """`current` with every change of an entry put back to its "before"."""
    value = current
    for ch in changes:
        value = set_path(value, tuple(ch["path"]), ch["before"])
    return value


def fingerprint(value):
    """A short stable stamp of a stored value, for stale-save detection."""
    import hashlib
    blob = json.dumps(value, sort_keys=True, default=repr)
    if not isinstance(blob, bytes):
        blob = blob.encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


# ── Zope: tracking and storage ───────────────────────────────────────────────

class _Tracked(object):
    """Per-transaction registry: {(store, key): {"before", "getter", "label"}}."""

    def __init__(self):
        self.items = {}
        self.actor = None
        self.note = None
        self.hooked = False


def _registry():
    import transaction
    txn = transaction.get()
    reg = txn.data(_Tracked) if _has_data(txn) else None
    if reg is None:
        reg = _Tracked()
        txn.set_data(_Tracked, reg)
    return txn, reg


def _has_data(txn):
    try:
        txn.data(_Tracked)
        return True
    except KeyError:
        return False


def set_actor(name):
    """Attribute this transaction's entries to `name` (e.g. "installer")."""
    _txn, reg = _registry()
    reg.actor = name


def set_note(note):
    """A note carried by this transaction's entries (e.g. "revert of <id>")."""
    _txn, reg = _registry()
    reg.note = note


def track(portal, store, key, getter, label=u"", action=u"", reason=u""):
    """Register a (store, key) about to be written in this transaction.
    `portal` may be None for stores that live outside the ZODB (files, SQLite).
    `action` names the act ("retire layout") and `reason` is the one the
    person gave; both are written on the entry when given."""
    try:
        if portal is None:
            from bika.lims import api
            portal = api.get_portal()
        txn, reg = _registry()
        ident = (store, u"%s" % key)
        if ident not in reg.items:
            reg.items[ident] = {"before": _safe(getter), "getter": getter,
                                "label": label, "portal": portal,
                                "action": action, "reason": reason}
        else:
            item = reg.items[ident]
            item["label"] = merge_label(item["label"], label)
            item["action"] = merge_label(item.get("action"), action)
            item["reason"] = merge_label(item.get("reason"), reason)
        if not reg.hooked:
            txn.addBeforeCommitHook(_write_entries, (reg,))
            reg.hooked = True
    except Exception as exc:                                        # noqa: BLE001
        if store in STRICT_STORES:
            raise HistoryNotRecorded(
                u"The change to %s %s was not saved: its history entry could not be "
                u"prepared (%s)." % (store, key, exc))
        # elsewhere history does not block the save it describes
        logger.warning("config_history.track(%s, %s): %s", store, key, exc)


def decode_json_strings(value):
    """JSON stored as text (a logbook's field schema) compared by meaning: the
    same schema re-serialised with its keys in another order is not a change."""
    if isinstance(value, dict):
        return dict((k, decode_json_strings(v)) for k, v in value.items())
    if isinstance(value, list):
        return [decode_json_strings(v) for v in value]
    if isinstance(value, basestring if str is bytes else str) and value.strip()[:1] in ("[", "{"):   # noqa: F821
        try:
            return decode_json_strings(json.loads(value))
        except ValueError:
            return value
    return value


_UNREADABLE = object()


def _safe(getter):
    """The value through `getter`, or _UNREADABLE: a value that cannot be read
    must not be recorded as "cleared", so the item is skipped (and logged)."""
    try:
        return decode_json_strings(json.loads(json.dumps(getter(), default=repr)))
    except Exception as exc:                                        # noqa: BLE001
        logger.warning("config_history: cannot read value: %s", exc)
        return _UNREADABLE


AT_FORMAT = "%Y-%m-%d %H:%M:%S"


def now():
    """The one audit time stamp: UTC, "YYYY-MM-DD HH:MM:SS" (sorts as text,
    as every entry's key does)."""
    return datetime.utcnow().strftime(AT_FORMAT)


def shown_at(at):
    """An entry's stored UTC time as the history shows it: on the
    laboratory's clock, in the stored form."""
    from senaite.pfas import lab_time
    return lab_time.show(at, "utc", AT_FORMAT)


def lab_day_window(day_from, day_to):
    """(since, until) for entries() and count() from From and To, typed as
    the laboratory's days ("YYYY-MM-DD"): the first second of the first day
    and the last second of the last day on the laboratory's clock, as UTC in
    the stored form, so that they compare as text. While the zone does not
    convert, or for text that is not a day, the text as typed (a bare date
    bound covers its whole day); an empty bound is None."""
    from datetime import timedelta
    from senaite.pfas import lab_time

    def bound(day, last):
        if not day:
            return None
        if not lab_time.active():
            return day
        try:
            start = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            return day
        if not last:
            return lab_time.to_utc(start).isoformat(" ")
        return (lab_time.to_utc(start + timedelta(days=1)) - timedelta(seconds=1)).isoformat(" ")

    return bound(day_from, False), bound(day_to, True)


def actor():
    """Who acts: this transaction's set_actor name, else the signed-in user's
    id, else "system"."""
    try:
        _txn, reg = _registry()
    except ImportError:         # outside Zope there is no transaction
        reg = None
    return _who(reg)


def _who(reg):
    if reg is not None and reg.actor:
        return reg.actor
    try:
        from bika.lims import api
        user = api.get_current_user()
        uid = user.getId() if user is not None else None
        return uid or u"system"
    except ImportError:         # outside SENAITE nobody is signed in
        return u"system"


def _write_entries(reg):
    """Before-commit hook: each tracked change becomes an entry for the
    transaction's writer. A strict store's failure is RAISED, which aborts
    the transaction and with it the save; any other store's is logged."""
    for (store, key), item in sorted(reg.items.items()):
        try:
            _write_one(reg, store, key, item)
        except Exception as exc:                                    # noqa: BLE001
            if store in STRICT_STORES:
                raise HistoryNotRecorded(
                    u"The change to %s %s was not saved: its history entry could "
                    u"not be written (%s)." % (store, key, exc))
            logger.error("config_history: entry for %s/%s not written: %s",
                         store, key, exc)


def _write_one(reg, store, key, item):
    after = _safe(item["getter"])
    if item["before"] is _UNREADABLE or after is _UNREADABLE:
        if store in STRICT_STORES:
            raise ValueError("the value before or after could not be read")
        logger.warning("config_history: %s/%s unreadable; no entry", store, key)
        return
    changes = diff(item["before"], after)
    if not changes:
        return
    entry = {
        "at": now(),
        "who": _who(reg), "store": store, "key": key, "label": item["label"],
        "changes": [{"path": list(p), "before": b, "after": a}
                    for p, b, a in changes],
    }
    if reg.note:
        entry["note"] = reg.note
    for field in ("action", "reason"):
        if item.get(field):
            entry[field] = item[field]
    if store in REDACTED_STORES:
        entry["changes"] = [{"path": list(p), "before": u"(redacted)",
                             "after": u"(redacted)"} for p, b, a in changes]
        entry["redacted"] = True
    _append(item["portal"], entry)


def db_path():
    return DB_PATH or os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


def _connect():
    """A connection that writes: the schema made or brought up first."""
    import sqlite3
    from senaite.pfas import qc_schema
    path = db_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    qc_schema.ensure(conn)
    return conn


def _reader():
    """A connection that reads, or None where there is no table yet: a read
    never makes the database or its schema."""
    import sqlite3
    from senaite.pfas import config_history_db as hdb
    path = db_path()
    if not os.path.isfile(path):
        return None
    conn = sqlite3.connect(path, timeout=30)
    if not hdb.has_table(conn):
        conn.close()
        return None
    return conn


def _write_now(entries):
    """Write (id, JSON text) pairs at once, in one transaction of their own."""
    from senaite.pfas import config_history_db as hdb
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            hdb.insert(conn, entries)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


class _Writer(object):
    """The data manager holding one transaction's entries. It votes last
    (sortKey), and writes them then: a conflict or a failure of any other
    resource's vote leaves the table untouched, and a failure here aborts
    the transaction when an entry is a strict store's."""

    transaction_manager = None

    def __init__(self):
        self.entries = []

    def sortKey(self):
        return "~senaite.pfas.config_history"

    def savepoint(self):
        return _WriterSavepoint(self)

    def abort(self, txn):
        self.entries = []

    def tpc_begin(self, txn):
        pass

    def commit(self, txn):
        pass

    def tpc_vote(self, txn):
        if not self.entries:
            return
        pairs = [(e["id"], json.dumps(e, sort_keys=True)) for e in self.entries]
        try:
            _write_now(pairs)
        except Exception as exc:                                    # noqa: BLE001
            strict = [e for e in self.entries if e.get("store") in STRICT_STORES]
            if strict:
                raise HistoryNotRecorded(
                    u"The change to %s %s was not saved: its history entry could not be "
                    u"written (%s)." % (strict[0].get("store"), strict[0].get("key"), exc))
            logger.error("config_history: %d entries not written: %s", len(pairs), exc)
        self.entries = []

    def tpc_finish(self, txn):
        self.entries = []

    def tpc_abort(self, txn):
        self.entries = []


class _WriterSavepoint(object):

    def __init__(self, writer):
        self.writer, self.n = writer, len(writer.entries)

    def rollback(self):
        del self.writer.entries[self.n:]


def _writer():
    """This transaction's writer, joined on first use; None outside Zope."""
    try:
        import transaction
    except ImportError:
        return None
    txn = transaction.get()
    try:
        return txn.data(_Writer)
    except KeyError:
        pass
    w = _Writer()
    txn.join(w)
    txn.set_data(_Writer, w)
    return w


def _append(portal, entry):
    eid = "%s-%s" % (entry["at"].replace(" ", "T"), uuid.uuid4().hex[:8])
    entry["id"] = eid
    try:
        w = _writer()
    except ValueError:
        # the transaction is past joining (an after-commit step): what the
        # entry describes is already committed, so it is written at once
        w = None
    if w is None:
        _write_now([(eid, json.dumps(entry, sort_keys=True))])
    else:
        w.entries.append(entry)
    return eid


def append(portal, entry):
    """Write an entry directly (used for reverts, which are their own act)."""
    entry.setdefault("at", now())
    return _append(portal, entry)


# ── the entries kept on the portal before the move ──────────────────────────

def _btree(portal, create=False):
    """The portal's own entries, or None. Only read: no entry is written
    here any more."""
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal).get(HISTORY_KEY)


def moved(portal):
    """The verified move's record ({"at", "count", "checksum"}), or None."""
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(portal).get(MOVED_KEY)
    except Exception:                                               # noqa: BLE001
        return None
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _legacy(portal):
    """The portal's entries while their move is not verified, else None."""
    if portal is None or moved(portal):
        return None
    try:
        return _btree(portal)
    except Exception:                                               # noqa: BLE001
        return None


def move_from_annotation(portal, apply=True):
    """Copy every entry kept on the portal into the table, then verify the
    copy by count and checksum over the portal's entries. Run again it adds
    nothing (a row already there is left as it is). Only a verified copy is
    marked moved (MOVED_KEY); the portal's entries are never removed here.
    With apply False nothing is written: the report says what the table
    holds now. Returns the report (config_history_db.verify, plus "copied",
    "applied" and "marked")."""
    from senaite.pfas import config_history_db as hdb
    tree = _btree(portal)
    pairs = [(eid, tree[eid]) for eid in tree.keys()] if tree else []
    copied = 0
    if apply:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                copied = hdb.insert(conn, pairs, ignore=True)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            report = hdb.verify(pairs, conn)
        finally:
            conn.close()
    else:
        conn = _reader()
        try:
            report = hdb.verify(pairs, conn)
        finally:
            if conn is not None:
                conn.close()
    report.update(copied=copied, applied=bool(apply), marked=False)
    if apply and report["ok"]:
        from zope.annotation.interfaces import IAnnotations
        IAnnotations(portal)[MOVED_KEY] = json.dumps(
            {"at": now(), "count": report["count_source"], "checksum": report["sum_source"]},
            sort_keys=True)
        report["marked"] = True
    return report


def _keep(e, store, key, since, until):
    if store and e.get("store") != store:
        return False
    if key and u"%s" % e.get("key") != u"%s" % key:
        return False
    at = u"%s" % (e.get("at") or u"")
    # "at" is "YYYY-MM-DD HH:MM:SS" (UTC): text order is time order; a bare
    # date bound covers its whole day
    if since and at < since:
        return False
    if until and at[:len(until)] > until:
        return False
    return True


def _legacy_entries(portal, store, key, since, until):
    tree = _legacy(portal)
    if not tree:
        return []
    out = []
    for eid in tree.keys():
        e = json.loads(tree[eid])
        if _keep(e, store, key, since, until):
            out.append(e)
    return out


def _merged(portal, store, key, since, until):
    """Every matching entry of the table and of the portal's unmoved ones,
    each once, newest first."""
    from senaite.pfas import config_history_db as hdb
    by_id = dict((e.get("id"), e) for e in _legacy_entries(portal, store, key, since, until))
    conn = _reader()
    if conn is not None:
        try:
            for e in hdb.select(conn, store, key, since, until):
                by_id[e.get("id")] = e
        finally:
            conn.close()
    return [by_id[k] for k in sorted(by_id, key=lambda x: u"%s" % x, reverse=True)]


def entries(portal, store=None, key=None, limit=200, since=None, until=None, offset=0):
    """Newest first, optionally for one store and/or key and a time window
    (since / until: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS", UTC), skipping the
    first `offset` that match."""
    from senaite.pfas import config_history_db as hdb
    if _legacy(portal):
        return _merged(portal, store, key, since, until)[offset:offset + limit]
    conn = _reader()
    if conn is None:
        return []
    try:
        return hdb.select(conn, store, key, since, until, limit=limit, offset=offset)
    finally:
        conn.close()


def count(portal, store=None, key=None, since=None, until=None):
    """How many entries match (for paging)."""
    from senaite.pfas import config_history_db as hdb
    if _legacy(portal):
        return len(_merged(portal, store, key, since, until))
    conn = _reader()
    if conn is None:
        return 0
    try:
        return hdb.count(conn, store, key, since, until)
    finally:
        conn.close()


def get_entry(portal, eid):
    from senaite.pfas import config_history_db as hdb
    conn = _reader()
    if conn is not None:
        try:
            found = hdb.get(conn, eid)
        finally:
            conn.close()
        if found is not None:
            return found
    tree = _legacy(portal)
    if tree and eid in tree:
        return json.loads(tree[eid])
    return None


def _newest(portal, store=None, key=None, since=None, until=None):
    """The matching entries, newest first."""
    if _legacy(portal):
        for e in _merged(portal, store, key, since, until):
            yield e
        return
    from senaite.pfas import config_history_db as hdb
    conn = _reader()
    if conn is None:
        return
    try:
        rows = hdb.select(conn, store, key, since, until)
    finally:
        conn.close()
    for e in rows:
        yield e


def last_change(portal, store, key, path=None):
    """The newest entry for one store and key; with `path` (a sequence of
    keys), the newest whose changes include that path exactly."""
    want = None if path is None else [u"%s" % p for p in path]
    for e in _newest(portal, store, key):
        if want is None or any([u"%s" % p for p in ch.get("path") or []] == want
                               for ch in e.get("changes") or []):
            return e
    return None


# ── store registry: how to read and save each store, for reverts ────────────
# A revert is applied through the store's OWN save function, so everything
# that save keeps in step (the worker's JSON export, AnalysisSpec sync, the
# method bridge) stays in step. Stores register at import.

STORES = {}
TITLES = {}      # display names for stores recorded but not revertable here


def register_store(name, getter, saver, title=u"", map_changes=None, as_saved=None):
    """getter(portal, key) -> stored value; saver(portal, key, value).
    map_changes(current, changes) -> (changes, refusal): an entry's changes
    as the store holds them now (a revert applies those); as_saved(value) ->
    the value as the saver would store it (a revert that would store nothing
    new is refused)."""
    STORES[name] = {"getter": getter, "saver": saver, "title": title or name,
                    "map_changes": map_changes, "as_saved": as_saved}


def stamp(value):
    """Version stamp of a stored value, ignoring what nobody edits: a form
    carries it, and a save whose stamp no longer matches is refused."""
    if isinstance(value, dict):
        value = dict((k, v) for k, v in value.items()
                     if k not in IGNORED_KEYS and k not in ("updated_at", "_seeded"))
    return fingerprint(value)


PANEL_KEY = "master_analyte_set"


def panel_change(changes):
    """The paths of `changes` (an entry's) that touch the analyte panel: the
    panel is the cache of the services' Method links, so such an entry is
    undone in Setup, never reverted from history."""
    return [u"/".join(u"%s" % x for x in ch["path"]) for ch in changes or []
            if ch.get("path") and ch["path"][0] == PANEL_KEY]


def merge_label(existing, new):
    """One transaction may save a value twice under two labels (a profile
    saved under its name, then its analyte links refreshed): the entry keeps
    both, the first first."""
    existing, new = existing or u"", new or u""
    if not existing or existing == new:
        return new or existing
    if not new:
        return existing
    return u"%s; %s" % (existing, new)


def revert(portal, eid):
    """Revert one entry through its store's save function. Returns (ok, msg)."""
    entry = get_entry(portal, eid)
    if not entry:
        return False, u"No such change."
    if entry.get("redacted"):
        return False, u"A redacted change cannot be reverted from history."
    spec = STORES.get(entry["store"])
    if spec is None:
        return False, u"This kind of setting cannot be reverted from history yet."
    if entry["store"] == "method_profile" and panel_change(entry.get("changes")):
        return False, (u"Not reverted: the analyte panel follows the services' Method "
                       u"links. Link or unlink the service in Setup (Analysis Services, "
                       u"Methods) and the panel follows.")
    current = spec["getter"](portal, entry["key"])
    changes = entry["changes"]
    if spec.get("map_changes"):
        changes, refusal = spec["map_changes"](current, changes)
        if refusal:
            return False, refusal
    bad = revert_conflicts(current, changes)
    if bad:
        return False, (u"Not reverted: a later change touched "
                       + u", ".join(u"/".join(u"%s" % x for x in p) for p in bad[:4])
                       + u". Revert the later change first.")
    value = reverted(current, changes)
    stored = spec["as_saved"](copy.deepcopy(value)) if spec.get("as_saved") else value
    if not diff(current, stored):
        return False, u"Not reverted: the stored setting would not change."
    set_note(u"revert of %s" % eid)
    spec["saver"](portal, entry["key"], value)
    return True, u"Reverted."
