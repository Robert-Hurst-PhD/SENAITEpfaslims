# -*- coding: utf-8 -*-
"""Drag-and-drop reordering by SortableJS (docs/REUSE_REVIEW.md U3): touch
screens work, and the hand-written HTML5 drag code is gone."""
from __future__ import unicode_literals

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
B = os.path.join(ROOT, "src", "senaite", "pfas", "browser")


def _read(*parts):
    with io.open(os.path.join(B, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_no_hand_written_html5_drag_code_left():
    for parts in (("templates", "run_builder.pt"), ("static", "method_profile_edit.js"),
                  ("templates", "method_profile_edit.pt")):
        src = _read(*parts)
        for ev in ("dragstart", "dragover", "dragend", "dataTransfer"):
            assert ev not in src, (parts, ev)
        assert not re.search(r'setAttribute\(.draggable.', src), parts
        assert "tal:attributes" not in src or "draggable python:" not in src, parts


def test_both_lists_use_sortable_and_keep_their_save_callbacks():
    rb = _read("templates", "run_builder.pt")
    assert "Sortable.create(list" in rb and "onEnd: serialize" in rb
    assert rb.index("vendor/Sortable-1.15.6.min.js") < rb.index("Sortable.create(list")
    js = _read("static", "method_profile_edit.js")
    assert "Sortable.create(stageList" in js
    assert "onEnd: function () { renumberStages(); syncStageJson(); }" in js
    tpl = _read("templates", "method_profile_edit.pt")
    assert tpl.index("vendor/Sortable-1.15.6.min.js") < tpl.index("method_profile_edit.js")
    assert os.path.exists(os.path.join(B, "static", "vendor", "Sortable-LICENSE.txt"))


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
