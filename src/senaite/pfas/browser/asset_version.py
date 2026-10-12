# -*- coding: utf-8 -*-
"""The version stamped on the add-on's stylesheet and script URLs.

Zope serves ++resource++senaite.pfas/* with a day's cache, so a browser kept
an old stylesheet for up to a day after a deploy while the pages' markup was
new: pages looked broken in a different way for each person. Every CSS / JS
URL the pages write carries ?v=<this>, the newest modification time of the
static files, so a deploy changes the URL and every browser fetches it anew.

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import os
import time

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RECHECK_SECONDS = 30
_CACHE = {"value": None, "at": 0.0}


def newest_mtime(root):
    newest = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith((".css", ".js")):
                try:
                    newest = max(newest, int(os.path.getmtime(os.path.join(base, name))))
                except OSError:
                    continue
    return newest


def asset_version(root=None, now=None):
    now = time.time() if now is None else now
    if root is not None:
        return "%x" % newest_mtime(root)
    if _CACHE["value"] is None or now - _CACHE["at"] > RECHECK_SECONDS:
        _CACHE["value"] = "%x" % newest_mtime(STATIC)
        _CACHE["at"] = now
    return _CACHE["value"]
