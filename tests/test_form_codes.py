# -*- coding: utf-8 -*-
"""Form numbers (DECISIONS 2026-10-02): FM-ENV-<logbook sequence>, each used
once, the pool in number order, and every label read from the pool -- the
storage slugs 250-253 are never shown as form numbers."""
from __future__ import unicode_literals

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import form_codes as fc    # noqa: E402

LIVE = [dict(slug="251", form_num="FM-ENV-002", builtin=True),
        dict(slug="custom-e9", form_num="FM-ENV-001", builtin=False),
        dict(slug="252", form_num="FM-ENV-003", builtin=True),
        dict(slug="253", form_num="FM-ENV-004", builtin=True),
        dict(slug="coc", form_num="COC", builtin=True),
        dict(slug="250", form_num="FM-ENV-001", builtin=True)]


def test_the_live_pool_is_numbered_and_ordered_as_decided():
    out, renamed = fc.normalise(LIVE)
    assert [(d["slug"], d["form_num"]) for d in out] == [
        ("250", "FM-ENV-001"), ("251", "FM-ENV-002"), ("252", "FM-ENV-003"),
        ("253", "FM-ENV-004"), ("custom-e9", "FM-ENV-005"), ("coc", "COC")]
    assert renamed == [("custom-e9", "FM-ENV-001", "FM-ENV-005")]
    again, renamed2 = fc.normalise(out)
    assert again == out and renamed2 == []                 # idempotent


def test_helpers():
    assert fc.number("FM-ENV-012") == 12 and fc.number(" fm-env-3 ") == 3
    assert fc.number("COC") is None and fc.number("") is None
    assert fc.next_code(["FM-ENV-001", "COC", "FM-ENV-004"]) == "FM-ENV-005"
    assert fc.next_code([]) == "FM-ENV-001"
    assert fc.duplicates(LIVE) == ["FM-ENV-001"]
    assert fc.duplicates([dict(form_num="fm-env-001"), dict(form_num="FM-ENV-001 ")]) == ["FM-ENV-001"]
    assert fc.duplicates(fc.normalise(LIVE)[0]) == []
    # two custom logbooks sharing a number: the first keeps it
    out, ren = fc.normalise([dict(slug="a", form_num="FM-ENV-007"), dict(slug="b", form_num="FM-ENV-007")])
    assert [d["form_num"] for d in out] == ["FM-ENV-007", "FM-ENV-008"] and ren == [("b", "FM-ENV-007", "FM-ENV-008")]


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    store = _src("logbook_store.py")
    save = store[store.index("def save_logbook_defs"):]
    save = save[:save.index("\ndef ", 1)]
    assert "dup = duplicates(defs)\n    if dup:\n        raise ValueError" in save, \
        "a form number used twice must be refused"
    assert save.index("raise ValueError") < save.index("normalise(defs)") < save.index("for i, d in enumerate(defs)")
    assert "def form_code(" in store and "def normalise_form_codes(" in store
    assert "normalise_form_codes(portal)" in _src("setuphandlers.py")
    lb = _src("browser", "logbooks.py")
    assert "next_code(" in lb, "a new logbook takes the next form number, not its slug"
    assert "move_up" not in _src("browser", "templates", "logbook_admin.pt")


def test_position_zero_is_first_not_last():
    """`int(sort_order or 100)` read position 0 back as 100, so FM-ENV-001
    was listed last everywhere."""
    for rel in (("logbook_store.py",), ("browser", "prep_logbooks.py")):
        text = _src(*rel)
        assert not re.search(r"sort_order[\"'\]]*\)?\s*or\s*100", text) and \
            not re.search(r'sort_order", 100\) or 100', text), rel
    assert "def sort_value(" in _src("browser", "prep_logbooks.py")


def test_no_slug_is_shown_as_a_form_number():
    bad = []
    for dirpath, _d, files in os.walk(PKG):
        for name in files:
            if not name.endswith((".pt", ".py", ".js")):
                continue
            path = os.path.join(dirpath, name)
            with io.open(path, encoding="utf-8") as fh:
                text = fh.read()
            if name.endswith(".pt"):
                text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
                hits = re.findall(r"FM-ENV-25[0-3]", text)
            else:
                # visible strings only: u"..." literals, not comments/docstrings
                hits = [m for m in re.findall(r"""u["'][^"'\n]*FM-ENV-25[0-3][^"'\n]*["']""", text)]
            if hits:
                bad.append("%s: %s" % (os.path.relpath(path, ROOT), hits[:2]))
    assert not bad, "\n".join(bad)


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
