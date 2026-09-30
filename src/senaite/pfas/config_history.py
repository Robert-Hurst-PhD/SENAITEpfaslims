# -*- coding: utf-8 -*-
"""Change history for laboratory configuration (docs/CONFIG_ARCHITECTURE_REVIEW.md, R1).

Every save of a configuration store records ONE entry per (store, key) per
transaction: who, when, and the path-level changes with the value before and
after. ISO 17025 §8.3 expects that record for acceptance criteria; before
this, a method profile was one JSON value overwritten on every save.

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
One OOBTree on the portal, keyed "<ISO timestamp>-<uuid>" so concurrent saves
never contend on a counter; each value is one JSON entry. ZODB rather than
SQLite on purpose (DECISIONS 2026-09-30): an entry must commit or roll back
WITH the change it describes, which a separate SQLite file cannot do.

The diff, apply and conflict functions are pure (no Zope) and shared with
tools/config_save_audit.py. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import copy
import json
import logging
import uuid
from datetime import datetime

logger = logging.getLogger("senaite.pfas.config_history")

HISTORY_KEY = "senaite.pfas.config_history"

# Keys nobody edits: timestamps, seeding markers and values the system derives.
# A change to one of these alone records nothing (they would bury real edits).
IGNORED_KEYS = frozenset(["updated_at", "_seeded", "matrix_uid_map",
                          "master_analyte_set", "display_analyte_set",
                          "method_id"])

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
            if not path and k in IGNORED_KEYS:
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


def track(portal, store, key, getter, label=u""):
    """Register a (store, key) about to be written in this transaction.
    `portal` may be None for stores that live outside the ZODB (files, SQLite)."""
    try:
        if portal is None:
            from bika.lims import api
            portal = api.get_portal()
        txn, reg = _registry()
        ident = (store, u"%s" % key)
        if ident not in reg.items:
            reg.items[ident] = {"before": _safe(getter), "getter": getter,
                                "label": label, "portal": portal}
        if not reg.hooked:
            txn.addBeforeCommitHook(_write_entries, (reg,))
            reg.hooked = True
    except Exception as exc:                                        # noqa: BLE001
        # History must never block the save it describes.
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


def _safe(getter):
    try:
        return decode_json_strings(json.loads(json.dumps(getter(), default=repr)))
    except Exception as exc:                                        # noqa: BLE001
        logger.warning("config_history: cannot read value: %s", exc)
        return None


def _who(reg):
    if reg.actor:
        return reg.actor
    try:
        from bika.lims import api
        user = api.get_current_user()
        uid = user.getId() if user is not None else None
        return uid or u"system"
    except Exception:
        return u"system"


def _write_entries(reg):
    for (store, key), item in sorted(reg.items.items()):
        after = _safe(item["getter"])
        changes = diff(item["before"], after)
        if not changes:
            continue
        entry = {
            "at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "who": _who(reg), "store": store, "key": key, "label": item["label"],
            "changes": [{"path": list(p), "before": b, "after": a}
                        for p, b, a in changes],
        }
        if reg.note:
            entry["note"] = reg.note
        if store in REDACTED_STORES:
            entry["changes"] = [{"path": list(p), "before": u"(redacted)",
                                 "after": u"(redacted)"} for p, b, a in changes]
            entry["redacted"] = True
        _append(item["portal"], entry)


def _btree(portal, create=True):
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    tree = ann.get(HISTORY_KEY)
    if tree is None and create:
        from BTrees.OOBTree import OOBTree
        tree = ann[HISTORY_KEY] = OOBTree()
    return tree


def _append(portal, entry):
    eid = "%s-%s" % (entry["at"].replace(" ", "T"), uuid.uuid4().hex[:8])
    entry["id"] = eid
    _btree(portal)[eid] = json.dumps(entry, sort_keys=True)
    return eid


def append(portal, entry):
    """Write an entry directly (used for reverts, which are their own act)."""
    entry.setdefault("at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    return _append(portal, entry)


def entries(portal, store=None, key=None, limit=200):
    """Newest first, optionally for one store and/or key."""
    tree = _btree(portal, create=False)
    if not tree:
        return []
    out = []
    for eid in reversed(list(tree.keys())):
        e = json.loads(tree[eid])
        if store and e.get("store") != store:
            continue
        if key and u"%s" % e.get("key") != u"%s" % key:
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


def get_entry(portal, eid):
    tree = _btree(portal, create=False)
    if not tree or eid not in tree:
        return None
    return json.loads(tree[eid])


def last_change(portal, store, key):
    found = entries(portal, store, key, limit=1)
    return found[0] if found else None


# ── store registry: how to read and save each store, for reverts ────────────
# A revert is applied through the store's OWN save function, so everything
# that save keeps in step (the worker's JSON export, AnalysisSpec sync, the
# method bridge) stays in step. Stores register at import.

STORES = {}
TITLES = {}      # display names for stores recorded but not revertable here


def register_store(name, getter, saver, title=u""):
    """getter(portal, key) -> stored value; saver(portal, key, value)."""
    STORES[name] = {"getter": getter, "saver": saver, "title": title or name}


def stamp(value):
    """Version stamp of a stored value, ignoring what nobody edits: a form
    carries it, and a save whose stamp no longer matches is refused."""
    if isinstance(value, dict):
        value = dict((k, v) for k, v in value.items()
                     if k not in IGNORED_KEYS and k not in ("updated_at", "_seeded"))
    return fingerprint(value)


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
    current = spec["getter"](portal, entry["key"])
    bad = revert_conflicts(current, entry["changes"])
    if bad:
        return False, (u"Not reverted: a later change touched "
                       + u", ".join(u"/".join(u"%s" % x for x in p) for p in bad[:4])
                       + u". Revert the later change first.")
    set_note(u"revert of %s" % eid)
    spec["saver"](portal, entry["key"], reverted(current, entry["changes"]))
    return True, u"Reverted."
