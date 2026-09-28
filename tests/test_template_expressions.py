# -*- coding: utf-8 -*-
"""Template expression forms that fail only when the branch is REACHED.

GAPS §40. `reagents.pt` carried

    href string:${view/portal_url}/...?action=coa&uid=${python:rg.get('uid','')}

from 2026-06-24. A `string:` expression may only interpolate a SIMPLE PATH, so
`${python:...}` inside one raises

    ExpressionError: $ must be doubled or followed by a simple path

and 500s the page. It sat there for three months because the branch renders only
inside `tal:condition="coa"` — and no reagent had a certificate of analysis on
file, so the expression was never evaluated. Attaching specimen CoAs (§37) made it
reachable, and the Reagent Inventory broke.

Nothing could have caught it at runtime: a page is only as tested as its data. A
STATIC scan catches it whatever the data, which is the point of this file.

Pure text and regex — no Zope, no Chameleon, so it runs in the standard suite.
"""
from __future__ import print_function

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
TEMPLATE_DIRS = [
    os.path.join(_ROOT, "src", "senaite", "pfas", "browser", "templates"),
    os.path.join(_ROOT, "src", "senaite", "pfas", "templates"),
]


def _templates():
    for base in TEMPLATE_DIRS:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name.endswith(".pt"):
                yield os.path.join(base, name)


def _strip_comments(body):
    """Blank out HTML comments, preserving line numbering.

    Necessary, not fastidious: the FIRST version of this test flagged the comment
    added to reagents.pt explaining the very defect it checks for. That is the
    third time in this codebase a raw-text scan has matched the prose describing
    a fix — tests/test_rule_toggles.py records the first, the ISO-date test the
    second. Strip the prose, scan the markup.
    """
    def _blank(match):
        return re.sub(r"[^\n]", " ", match.group(0))
    return re.sub(r"<!--.*?-->", _blank, body, flags=re.S)


# ── The defect ───────────────────────────────────────────────────────────────

def test_no_string_expression_interpolates_a_python_expression():
    """`${python:...}` inside `string:` — an ExpressionError at render time."""
    bad = []
    for path in _templates():
        with open(path) as fh:
            body = _strip_comments(fh.read())
        # Scan whole lines: a string: expression frequently wraps, so an
        # attribute-value scan alone would miss the multi-line cases.
        for lineno, line in enumerate(body.splitlines(), start=1):
            if "string:" not in line:
                continue
            after = line.split("string:", 1)[1]
            if "${python:" in after:
                bad.append("%s:%d" % (os.path.basename(path), lineno))
    assert not bad, (
        "`${python:...}` inside a `string:` expression raises ExpressionError "
        "when the branch renders: %s. Bind the value with tal:define and "
        "interpolate the simple path instead." % bad)


def test_no_interpolation_of_a_non_path_expression_type():
    """The same trap with the other expression prefixes. `${...}` takes a path;
    `python:`, `string:` and `structure` are all invalid inside it."""
    bad = []
    for path in _templates():
        with open(path) as fh:
            body = _strip_comments(fh.read())
        for lineno, line in enumerate(body.splitlines(), start=1):
            for prefix in ("${python:", "${string:", "${structure ",
                           "${nocall:"):
                if prefix in line:
                    bad.append("%s:%d %s" % (os.path.basename(path), lineno,
                                             prefix))
    assert not bad, (
        "`${...}` interpolates a SIMPLE PATH only; these use an expression "
        "type inside it: %s" % sorted(set(bad)))


def test_the_coa_link_uses_a_bound_path():
    """The specific site, pinned. Its uid must come from tal:define, because the
    inline python form is what broke the Reagent Inventory."""
    path = os.path.join(_ROOT, "src", "senaite", "pfas", "browser",
                        "templates", "reagents.pt")
    with open(path) as fh:
        body = fh.read()
    assert "rg_uid python:rg.get('uid','')" in body, (
        "reagents.pt no longer binds rg_uid, so the CoA href is probably "
        "interpolating a python: expression again")
    assert "uid=${rg_uid}" in body
    assert "uid=${python:" not in body


def test_no_tal_define_reads_the_repeat_variable_it_declares():
    """`tal:define` executes BEFORE `tal:repeat` on the SAME element.

    `facility_balance.pt` carried

        <tal:each tal:repeat="wp view/weight_points" tal:define="i repeat/wp/index">

    which raises at render time:

        LocationError: (RepeatDictWrapper, 'wp')

    because `repeat['wp']` does not exist while the define runs. The page 500'd for
    every selected balance from the day it was written, and nobody saw it: the whole
    form sits inside `tal:condition="unit"` and `facility_units` held zero rows, so
    no balance could be selected. Registering the first balance revealed it — the
    same latency as the CoA link above, by a different mechanism.

    The fix is to define the variable on a CHILD element, where the repeat variable
    exists. Static, so it holds with no units registered at all.
    """
    tag_re = re.compile(r"""<[^>]*tal:repeat\s*=\s*["'][^"']+["'][^>]*>""", re.S)
    rep_re = re.compile(r"""tal:repeat\s*=\s*["']\s*([A-Za-z_][\w.-]*)""")
    def_re = re.compile(r"""tal:define\s*=\s*["']([^"']*)["']""", re.S)
    bad = []
    for path in _templates():
        with open(path) as fh:
            body = _strip_comments(fh.read())
        # One element may span lines, so scan tag by tag, not line by line.
        for match in tag_re.finditer(body):
            tag = match.group(0)
            if "tal:define" not in tag:
                continue
            rep = rep_re.search(tag)
            define = def_re.search(tag)
            if not rep or not define:
                continue
            var = rep.group(1)
            reads = re.compile(r"""\brepeat[/\[]["']?%s\b""" % re.escape(var))
            if reads.search(define.group(1)):
                lineno = body.count("\n", 0, match.start()) + 1
                bad.append("%s:%d (repeat/%s)"
                           % (os.path.basename(path), lineno, var))
    assert not bad, (
        "tal:define runs before tal:repeat on the same element, so these read a "
        "repeat variable that does not exist yet and raise LocationError when the "
        "branch renders: %s. Move the define onto a child element." % bad)


def _strip_js_comments(body):
    """Blank `/* ... */` and `// ...` runs, preserving line numbering.

    Needed for the same reason `_strip_comments` is: the comments written to
    explain the root-relative URL defect CONTAIN a root-relative URL. Fourth
    occurrence of that trap in this codebase.
    """
    def _blank(match):
        return re.sub(r"[^\n]", " ", match.group(0))
    body = re.sub(r"/\*.*?\*/", _blank, body, flags=re.S)
    return re.sub(r"(?m)(?<![:\w])//[^\n]*$", _blank, body)


def test_no_view_url_is_relative_to_the_server_root():
    """`/@@some-view` resolves against the ZOPE root, not the Plone site.

    Zope serves the site at `/senaite`, and nginx roots VirtualHostMonster there
    too, so a root-relative view URL reaches neither: 500 direct (no `portal_url`
    tool on the Zope root) and 404 through nginx. Four sites carried this, and the
    lot-reference autocomplete was one — it had never opened in this deployment,
    which is also why nobody noticed the picker offering lots the release gate
    rejects (GAPS §41).

    Build the URL from `view/portal_url` (or `PORTAL_URL` in JS).
    """
    bad = []
    targets = list(_templates())
    js_dir = os.path.join(_ROOT, "src", "senaite", "pfas", "browser", "static")
    if os.path.isdir(js_dir):
        targets += [os.path.join(js_dir, n) for n in sorted(os.listdir(js_dir))
                    if n.endswith(".js")]
    assert targets, "no templates or scripts found — the scan is broken"
    # Two forms. JS: `'/@@view'` — the path opens a quoted string. TAL:
    # `string:/@@view"` — the path FOLLOWS `string:` and the quote is at the far
    # end of the attribute, so a quote-anchored pattern misses it entirely. The
    # first version of this test matched only the JS form and passed happily with
    # the real defect reinstated; the mutation check is what caught that.
    pattern = re.compile(r"""(?:["']|string:)(/@@[\w.-]+)""")
    for path in targets:
        with open(path) as fh:
            body = _strip_js_comments(_strip_comments(fh.read()))
        for m in pattern.finditer(body):
            # `PORTAL_URL + '/@@view'` is CORRECT — the string is a suffix, and the
            # concatenation may sit on the previous line, so look back through the
            # whole body rather than within the line. Scanning line by line flagged
            # eight valid sites, including the fix for this very defect.
            before = body[:m.start()].rstrip()
            if before.endswith("+"):
                continue
            lineno = body.count("\n", 0, m.start()) + 1
            bad.append("%s:%d %s"
                       % (os.path.basename(path), lineno, m.group(1)))
    assert not bad, (
        "these view URLs are relative to the SERVER root, which is not the Plone "
        "site: %s. Prefix with view/portal_url (TAL) or PORTAL_URL (JS)." % bad)


# NOTE: a "metal:fill-slot must not nest" check was attempted here and removed.
# A regex depth-count flagged 150 lines across 50 templates, every one of them
# valid — `<tal:styles metal:fill-slot="head-extra">` and friends confounded it
# completely. A check that cannot tell a valid template from an invalid one is
# worse than no check, and nesting is already caught by compiling the template
# (which is how §39 caught it on the pipette page). Left as a comment so the next
# person does not spend the same hour on it.


if __name__ == "__main__":
    ok = fail = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                fail += 1
                print("FAIL", name, "--", exc)
            except Exception as exc:
                fail += 1
                print("ERROR", name, "--", repr(exc))
            else:
                ok += 1
                print("PASS", name)
    print("{0} passed, {1} failed".format(ok, fail))
    if fail:
        sys.exit(1)
