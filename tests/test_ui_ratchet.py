# -*- coding: utf-8 -*-
"""The UI may only converge: page-local styling can shrink, never grow.

GAPS §49. The 2026-09-30 audit crawled 60 pages and found the shared layout
(pfas_macros.pt) was barely used: 51 screen templates carried their own
<style> block, drawing about ten different content frames and 63 button
classes. Consolidation happens a sidebar group at a time, so this test pins
the counts as they stand and fails if any of them rises. When a phase lowers
a count, lower the ceiling here in the same commit -- a ceiling left above the
real value lets the drift back in unnoticed.

Also pinned: a template that fills the macro's `title` slot must do so on a
<title> element. Filling it with bare text replaced the <title> tag, ended
<head> early, and rendered all three role landings unstyled.

Print templates (certificates, labels, receipts) are excluded: their point
sizes are deliberate and belong to the printed page, not the screen system.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "templates")

PRINT = {"receipt.pt", "label_print.pt", "qc_review_report.pt",
         "coa_attestation.pt"}
SHARED = {"pfas_macros.pt", "pfas_sidebar.pt"}

# Ceilings, measured 2026-09-30. Lower them as consolidation lands; never raise.
MAX_PAGES_WITH_STYLE_BLOCK = 51
MAX_STYLE_ATTRIBUTES = 968
MAX_DISTINCT_HEX = 223
MAX_DISTINCT_FONT_SIZES = 23


def _screen_templates():
    for name in sorted(os.listdir(TEMPLATES)):
        if name.endswith(".pt") and name not in PRINT:
            with open(os.path.join(TEMPLATES, name)) as fh:
                yield name, fh.read()


def _counts():
    pages = attrs = 0
    hexes, sizes = set(), set()
    for name, text in _screen_templates():
        if name not in SHARED and "<style" in text:
            pages += 1
        attrs += text.count('style="')
        hexes.update(h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,6}\b", text))
        for v in re.findall(r"(?<![-\w])font-size\s*:\s*([^;\"}]+)", text):
            sizes.add(v.replace("!important", "").strip())
    return pages, attrs, len(hexes), len(sizes)


def test_page_local_style_blocks_do_not_grow():
    pages = _counts()[0]
    assert pages <= MAX_PAGES_WITH_STYLE_BLOCK, (
        "{0} pages carry their own <style> (ceiling {1}); use the shared "
        "classes in pfas_macros.pt".format(pages, MAX_PAGES_WITH_STYLE_BLOCK))


def test_inline_style_attributes_do_not_grow():
    attrs = _counts()[1]
    assert attrs <= MAX_STYLE_ATTRIBUTES, (
        "{0} style= attributes (ceiling {1})".format(attrs, MAX_STYLE_ATTRIBUTES))


def test_hex_colours_do_not_grow():
    n = _counts()[2]
    assert n <= MAX_DISTINCT_HEX, (
        "{0} distinct hex colours (ceiling {1}); use a var(--s-*) token".format(
            n, MAX_DISTINCT_HEX))


def test_font_sizes_do_not_grow():
    n = _counts()[3]
    assert n <= MAX_DISTINCT_FONT_SIZES, (
        "{0} distinct font sizes (ceiling {1})".format(n, MAX_DISTINCT_FONT_SIZES))


def test_title_slot_is_filled_on_a_title_element():
    bad = []
    for name, text in _screen_templates():
        for m in re.finditer(r"<([\w:]+)[^>]*(?<![\w-])(?:metal:)?fill-slot=\"title\"", text):
            if m.group(1) != "title":
                bad.append("{0}: <{1}>".format(name, m.group(1)))
    assert not bad, "title slot filled without a <title> element: {0}".format(bad)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("counts (pages, style=, hex, font-size):", _counts())
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
