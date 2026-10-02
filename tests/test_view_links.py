# -*- coding: utf-8 -*-
"""Every @@pfas-* view a template, script or module links to is registered.

A misspelt view name is a link to a 404 that no other test notices: the
Bench page shipped a button to @@pfas-prepared-standards (the view is
@@pfas-prep-standards) and every suite stayed green."""
from __future__ import unicode_literals

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")

# not followed by "-" or "{": "@@pfas-logbook-{1}" is a format string, not a link
LINK = re.compile(r"@@(pfas-[a-z0-9][a-z0-9-]*[a-z0-9])(?![-{\w])")


def _walk(exts):
    for dirpath, _dirs, files in os.walk(PKG):
        if "__pycache__" in dirpath:
            continue
        for name in files:
            if name.endswith(exts):
                yield os.path.join(dirpath, name)


def registered():
    names = set()
    for path in _walk((".zcml",)):
        with io.open(path, encoding="utf-8") as fh:
            names.update(re.findall(r'\bname="(pfas-[^"]+)"', fh.read()))
    return names


def test_every_pfas_view_link_is_registered():
    names = registered()
    assert len(names) > 50, "the ZCML scan found too few views to be trusted"
    missing = []
    for path in _walk((".pt", ".py", ".js")):
        with io.open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                for view in LINK.findall(line):
                    # the sidebar's active-item test matches a PREFIX of a path
                    prefix = " in path" in line and any(r.startswith(view) for r in names)
                    if view not in names and not prefix:
                        missing.append("%s:%d @@%s" % (os.path.relpath(path, ROOT), n, view))
    assert not missing, "links to unregistered views:\n  " + "\n  ".join(missing)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
