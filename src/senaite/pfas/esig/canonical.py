# -*- coding: utf-8 -*-
"""The one canonical JSON form every signature hash and ledger entry uses.

Keys sorted, no spaces, non-ASCII escaped, over unicode text, ints, floats,
lists, dicts and null only. Python 2.7 and 3 produce the same text, so the
add-on and the worker agree on every hash. A value JSON cannot hold raises.
"""
from __future__ import absolute_import, unicode_literals

import hashlib
import json


def dumps(obj):
    """The canonical JSON text of obj, as unicode."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)
    if isinstance(text, bytes):
        text = text.decode("ascii")
    return text


def sha256_bytes(data):
    """The sha256 hex of bytes, as unicode."""
    h = hashlib.sha256(data).hexdigest()
    if isinstance(h, bytes):
        h = h.decode("ascii")
    return h


def sha256_of(obj):
    """The sha256 hex of the canonical JSON of obj, as unicode."""
    return sha256_bytes(dumps(obj).encode("utf-8"))
