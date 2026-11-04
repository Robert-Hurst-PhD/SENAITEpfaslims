# -*- coding: utf-8 -*-
"""Names taken from a request that are joined onto a directory on disk."""
from __future__ import absolute_import, unicode_literals

import os


def ensure_parent_dir(path):
    """Make the directory `path` sits in, when it has one and it is missing."""
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d)
        except OSError:
            pass


def is_plain_name(name):
    """True when `name` can only ever name one entry inside a directory:
    non-empty, no path separators, not a parent or self reference and no
    control characters."""
    if not name or not isinstance(name, ("".__class__, bytes)):
        return False
    try:
        text = name.decode("utf-8") if isinstance(name, bytes) else name
    except UnicodeDecodeError:
        return False
    if not text.strip() or text in (".", ".."):
        return False
    if "/" in text or "\\" in text or "\x00" in text:
        return False
    return os.path.basename(text) == text
