# -*- coding: utf-8 -*-
"""Charts: one Chart.js version across pages, limit bands by
chartjs-plugin-annotation instead of a hand-written plugin
(docs/REUSE_REVIEW.md U4)."""
from __future__ import unicode_literals

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
T = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "templates")


def _templates():
    for name in sorted(os.listdir(T)):
        if name.endswith(".pt"):
            with io.open(os.path.join(T, name), encoding="utf-8") as fh:
                yield name, fh.read()


def test_one_chart_js_version():
    versions = set()
    for _name, text in _templates():
        versions.update(re.findall(r"chart\.js@([0-9.]+)", text))
    assert len(versions) == 1, versions


def test_bands_come_from_the_annotation_plugin():
    with io.open(os.path.join(T, "calibrations.pt"), encoding="utf-8") as fh:
        cal = fh.read()
    assert "zoneBg" not in cal and "limitLineDatasets" not in cal
    assert cal.count("annotations: zoneAnnotations(") == 2
    assert cal.index("chart.umd.min.js") < cal.index("chartjs-plugin-annotation-3.1.0.min.js")
    assert os.path.exists(os.path.join(ROOT, "src", "senaite", "pfas", "browser", "static",
                                       "vendor", "chartjs-plugin-annotation-LICENSE.txt"))


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
