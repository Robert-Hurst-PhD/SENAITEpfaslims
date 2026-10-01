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
MAX_STYLE_ATTRIBUTES = 860
MAX_DISTINCT_HEX = 208
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


def test_no_python_expression_inside_a_string_expression():
    """Chameleon refuses "string:...${python:...}" and the whole page 500s --
    which happened twice, the second time only on the one method (1633A) whose
    tab rendered the offending line, so every other page still looked fine."""
    bad = []
    for folder in (TEMPLATES, os.path.join(TEMPLATES, "reports")):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.endswith(".pt"):
                with open(os.path.join(folder, name)) as fh:
                    body = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)   # prose about it is fine
                for m in re.finditer(r"string:[^;\"]*\$\{python:", body):
                    bad.append("%s: %s" % (name, body[m.start():m.start() + 60]))
    assert not bad, bad


def test_tal_attributes_split_cleanly():
    """tal:attributes separates attributes with ";" -- a ";" inside an
    expression (e.g. "return false;") splits it, and the page 500s. Found
    live on the QC Types tab (2026-10-01). Each part must be "name expr";
    ";;" is the escape."""
    bad = []
    for folder in (TEMPLATES, os.path.join(TEMPLATES, "reports")):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.endswith(".pt"):
                continue
            with open(os.path.join(folder, name)) as fh:
                body = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
            for m in re.finditer(r'tal:attributes="([^"]*)"', body):
                # the XML parser decodes entities (&amp; &quot;) BEFORE TAL
                # splits, so decode them first, exactly as Zope does
                try:
                    from html import unescape
                except ImportError:                        # Py2.7
                    from HTMLParser import HTMLParser
                    unescape = HTMLParser().unescape
                value = unescape(m.group(1)).replace(";;", "\x00")
                for part in value.split(";"):
                    if part.strip() and not re.match(r"^\s*[\w:.-]+\s+\S", part):
                        bad.append("%s: %r" % (name, part.strip()[:50]))
    assert not bad, bad


def test_links_are_buttons_not_text():
    """Lab, 2026-10-01: "Avoid the use of hyperlinks on text ... use a dedicated
    button on the text or next to the text." Every <a> on a PFAS page is a
    button (btn-*), a tab, a card / tile / row, or a pill picker -- never an
    underlined word in a sentence. Navigation chrome (sidebar, header menu,
    wizard stepper) and the printed certificate are exempt."""
    exempt = {"pfas_sidebar.pt", "pfas_macros.pt", "coa_sections.pt", "method_wizard.pt"}
    ok_class = re.compile(r"\b(btn|btn-[\w-]+|pfas-tab|pfas-ws-card|lb-card|bq-row|pfas-tile-link|tile|"
                          r"dr-tab|dev-tab|egad-tab|sop-tab|is-on|lbg-seg|row-pill)\b")
    bad = []
    for name in sorted(os.listdir(TEMPLATES)):
        if not name.endswith(".pt") or name in exempt:
            continue
        with open(os.path.join(TEMPLATES, name)) as fh:
            raw = fh.read()
        body = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), raw, flags=re.S)
        for m in re.finditer(r"<a\b([^>]*)>", body):
            attrs = m.group(1)
            if ok_class.search(attrs):
                continue
            if "'active' if" in attrs or "is-on" in attrs:      # pill pickers / segmented
                continue
            line = raw.count("\n", 0, m.start()) + 1
            bad.append("%s:%d" % (name, line))
    assert not bad, "text links (make them buttons): %s" % bad


def test_the_typeface_is_served_from_the_addon():
    """Nunito (decided 2026-09-30) is bundled, with its licence, and named
    first in --font-sans; no page may load a font from a third-party CDN
    (offline labs, and no lab page should call out to one)."""
    with open(os.path.join(STATIC, "pfas-tokens.css")) as fh:
        tokens = fh.read()
    # one family, three roles (2026-10-01): headers / body / subtitles
    assert re.search(r'--font-heading:\s*"Nunito"', tokens), "headers are not Nunito"
    assert re.search(r'--font-sans:\s*"Nunito Sans"', tokens), "body is not Nunito Sans"
    assert re.search(r'--font-subtitle:\s*"Nunito Sans"', tokens), "subtitles are not Nunito Sans"
    for url in re.findall(r'url\("([^"]+)"\)', tokens):
        assert not url.startswith(("http", "//")), url
        assert os.path.isfile(os.path.join(STATIC, url)), "missing font file %s" % url
    assert os.path.isfile(os.path.join(STATIC, "fonts", "OFL.txt")), "font licence not shipped"
    assert os.path.isfile(os.path.join(STATIC, "fonts", "OFL-NunitoSans.txt")), "Nunito Sans licence not shipped"
    for folder in (TEMPLATES, STATIC):
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.endswith((".pt", ".css", ".js")):
                with open(path) as fh:
                    body = fh.read()
                for cdn in ("fonts.googleapis", "fonts.gstatic", "use.typekit", "fontsource"):
                    assert cdn not in body, "%s loads fonts from %s" % (name, cdn)


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
