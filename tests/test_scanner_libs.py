# -*- coding: utf-8 -*-
"""R11 (docs/BENCH_WORKFLOW_REVIEW.md): the scanners run on @zxing/browser
0.2.1 (@zxing/library 0.23.0) and tesseract.js 7.0.0, pinned. @zxing/library
and tesseract.js are Apache-2.0, which is not GPLv2-compatible, so they are
loaded in the browser from a CDN and never vendored into this repository."""
from __future__ import unicode_literals

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BROWSER = os.path.join(ROOT, "src", "senaite", "pfas", "browser")


def _src(*parts):
    with io.open(os.path.join(BROWSER, *parts), encoding="utf-8") as fh:
        return fh.read()


PAGES = (("templates", "reagents.pt"), ("templates", "extraction_guide.pt"))


def test_pinned_versions_and_new_api():
    for page in PAGES:
        t = _src(*page)
        assert "@zxing/library@0.23.0/" in t and "@zxing/browser@0.2.1/" in t, page
        assert "@zxing/library@0.19" not in t and "tesseract.js@2" not in t, page
        assert "new ZXing.BrowserMultiFormatReader" not in t, page
        assert not re.search(r"(_codeReader|_scanReader)\.reset\(", t), \
            "@zxing/browser has no reader.reset(); stop the returned controls"
        assert ".then(function(c) {" in t, "the controls must be kept to stop the camera"
    assert "tesseract.js@7.0.0/" in _src("templates", "reagents.pt")


def test_apache_licensed_libraries_are_not_vendored():
    vend = os.path.join(BROWSER, "static", "vendor")
    for name in os.listdir(vend):
        low = name.lower()
        assert "zxing" not in low and "tesseract" not in low, name


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
