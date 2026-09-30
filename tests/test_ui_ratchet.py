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
BROWSER = os.path.join(ROOT, "src", "senaite", "pfas", "browser")
TEMPLATES = os.path.join(BROWSER, "templates")
STATIC = os.path.join(BROWSER, "static")
TOKENS = "pfas-tokens.css"

PRINT = {"receipt.pt", "label_print.pt", "qc_review_report.pt",
         "coa_attestation.pt", "coa_sections.pt"}
SHARED = {"pfas_macros.pt", "pfas_sidebar.pt"}

# Ceilings, measured 2026-09-30. Lower them as consolidation lands; never raise.
MAX_PAGES_WITH_STYLE_BLOCK = 51
MAX_STYLE_ATTRIBUTES = 940
MAX_DISTINCT_HEX = 209
MAX_DISTINCT_FONT_SIZES = 3   # the 36-64px display glyphs; all text uses var(--fs-*)


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
            v = v.replace("!important", "").strip()
            if not v.startswith("var(--fs-"):   # a type-scale token is the goal
                sizes.add(v)
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


def _all_styles():
    for name in sorted(os.listdir(TEMPLATES)):
        if name.endswith(".pt"):
            with open(os.path.join(TEMPLATES, name)) as fh:
                yield "templates/" + name, fh.read()
    for name in sorted(os.listdir(STATIC)):
        if name.endswith(".css"):
            with open(os.path.join(STATIC, name)) as fh:
                yield "static/" + name, fh.read()


def test_tokens_are_defined_once():
    """The palette was typed out in the macro AND the core overlay ("keep in
    sync"). A shared token is defined in pfas-tokens.css and nowhere else."""
    with open(os.path.join(STATIC, TOKENS)) as fh:
        shared = set(re.findall(r"(--[\w-]+)\s*:", fh.read()))
    assert "--s-primary" in shared and "--frame-gutter-x" in shared
    dupes = []
    for where, text in _all_styles():
        if where.endswith(TOKENS):
            continue
        for tok in re.findall(r"(--[\w-]+)\s*:", text):
            if tok in shared:
                dupes.append("{0}: {1}".format(where, tok))
    assert not dupes, "shared tokens redefined outside {0}: {1}".format(TOKENS, dupes)


def test_no_page_resizes_the_shared_frame():
    """.page-body / .page-body-narrow are the frame (CLAUDE.md §6C). A page that
    re-declares them brings back a private width -- the method profile editor
    capped itself at 900px this way."""
    bad = []
    for name, text in _screen_templates():
        if name == "pfas_macros.pt":
            continue
        for css in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S):
            css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if re.search(r"\.page-body(-narrow)?\b", sel) and re.search(
                        r"(max-)?width|margin|padding", body):
                    bad.append("{0}: {1}".format(name, sel.strip()))
        for m in re.finditer(r"<[^>]*class=\"page-body(?:-narrow)?\"[^>]*style=\"([^\"]*)\"", text):
            if re.search(r"width|margin|padding", m.group(1)):
                bad.append("{0}: inline style on .page-body".format(name))
    # tracker.pt is the client-facing tracker: no sidebar, no frame (§6C).
    bad = [b for b in bad if not b.startswith("tracker.pt")]
    assert not bad, "page re-declares the frame: {0}".format(bad)


# Names the shared layout owns. A page rule for one of these overrides the
# component everywhere on that page -- Reagent Inventory turned .btn-sm into a
# rounded pill, which is why its buttons matched nothing else.
SHARED_COMPONENTS = ("btn", "btn-sm", "btn-save", "btn-primary", "btn-secondary",
                     "btn-danger", "btn-warn", "btn-link", "btn-success", "badge",
                     "status-badge", "pfas-table", "pfas-tabs", "pfas-tab")
# Pages still carrying such overrides. Emptied 2026-09-30 when the last group
# was migrated (it started at 16); keep it empty.
REDEFINES_ALLOWED = set()


def _redefiners():
    found = {}
    for name, text in _screen_templates():
        if name in SHARED:
            continue
        for css in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S):
            css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            for sel, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                for c in SHARED_COMPONENTS:
                    if re.search(r"\." + re.escape(c) + r"(?![\w-])", sel):
                        found.setdefault(name, set()).add(c)
    return found


def test_no_new_page_redefines_a_shared_component():
    found = _redefiners()
    new = sorted(set(found) - REDEFINES_ALLOWED)
    assert not new, "pages redefine shared components: {0}".format(
        dict((n, sorted(found[n])) for n in new))


def test_redefine_allowlist_is_not_stale():
    stale = sorted(REDEFINES_ALLOWED - set(_redefiners()))
    assert not stale, "migrated -- remove from REDEFINES_ALLOWED: {0}".format(stale)


def test_no_double_hyphen_in_html_comments():
    """Chameleon refuses to compile a template whose HTML comment contains
    '--'. One such comment in pfas_sidebar.pt broke every page on the site
    (the sidebar renders on all of them) until it was found, 2026-09-30."""
    bad = []
    reports = os.path.join(ROOT, "src", "senaite", "pfas", "templates", "reports")
    paths = [os.path.join(TEMPLATES, n) for n in sorted(os.listdir(TEMPLATES))]
    paths += [os.path.join(reports, n) for n in sorted(os.listdir(reports))]
    for path in paths:
        name = os.path.basename(path)
        if not name.endswith(".pt"):
            continue
        with open(path) as fh:
            text = fh.read()
        for m in re.finditer(r"<!--(.*?)-->", text, re.S):
            if "--" in m.group(1):
                bad.append("{0}: {1}".format(name, m.group(1).strip()[:50]))
    assert not bad, "'--' inside an HTML comment: {0}".format(bad)


def test_text_uses_the_type_scale():
    """GAPS §49.10: 23 font sizes (9-28px) became the seven --fs-* tokens,
    matched to core's 14px body text. A literal size below 32px (display
    glyphs are larger) or a font family other than the tokens is drift."""
    bad = []
    for name, text in _screen_templates():
        for m in re.finditer(r"(?<![-\w])font-size\s*:\s*(\d+(?:\.\d+)?)(px|pt|em|rem)", text):
            if m.group(2) != "px" or float(m.group(1)) < 32:
                bad.append("{0}: {1}".format(name, m.group(0)))
        for m in re.finditer(r"font-family\s*:\s*([^;\"}]+)", text):
            v = m.group(1).strip()
            if not (v.startswith("var(--font-") or v == "inherit" or "Font Awesome" in v):
                bad.append("{0}: font-family {1}".format(name, v[:40]))
    assert not bad, "{0} off-scale: {1}".format(len(bad), bad[:8])


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
