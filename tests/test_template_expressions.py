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
