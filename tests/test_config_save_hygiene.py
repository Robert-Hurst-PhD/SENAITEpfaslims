# -*- coding: utf-8 -*-
"""Saving a configuration page must record only what the lab entered.

GAPS §51. A plain Save of the Method Profile editor stored an injection IS and a
confirmation technique nobody chose: the page showed a derived default IN the
field (by template or by script) and the handler saved it back. The sweep that
followed found the same family elsewhere:

  * a checkbox read as form.get(key, True) -- unchecked boxes are not
    submitted, so the option could never be switched off;
  * a number that fails to parse silently becoming a default (a matrix or
    salt factor typed "0,95" became 1.0 and removed a correction from
    reported results).

Pinned statically here; the live no-op-save audit (tools/config_save_audit.py)
checks the behaviour end to end.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.path.join(ROOT, "src", "senaite", "pfas", "browser")
TEMPLATES = os.path.join(BROWSER, "templates")
STATIC = os.path.join(BROWSER, "static")
FORM_NAMES = re.compile(r"^(f|form|self\.request\.form|request\.form)$")

# Revision counters on logbook/publication records: cosmetic, not a setting.
COERCION_ALLOWED = {("controlled_publications.py", "revision"),
                    ("logbooks.py", "rev_num"), ("prep_logbooks.py", "sort_order"),
                    ("prep_logbooks.py", "obj.sort_order"),
                    ("prep_logbooks.py", "obj.default_expiry_days"),
                    ("prepared_standards.py", "obj.logbook_revision")}


def _py():
    for name in sorted(os.listdir(BROWSER)):
        if name.endswith(".py"):
            with open(os.path.join(BROWSER, name)) as fh:
                src = fh.read()
            yield name, src, ast.parse(src)


def test_no_checkbox_defaults_to_true():
    bad = []
    for name, src, tree in _py():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and len(node.args) == 2
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value is True
                    and FORM_NAMES.match(ast.get_source_segment(src, node.func.value) or "")):
                bad.append("{0}:{1}".format(name, node.lineno))
    assert not bad, "form checkbox read with default True: {0}".format(bad)


def test_templates_show_defaults_as_placeholders_not_values():
    bad = []
    for name in sorted(os.listdir(TEMPLATES)):
        if not name.endswith(".pt"):
            continue
        with open(os.path.join(TEMPLATES, name)) as fh:
            text = fh.read()
        for m in re.finditer(r"\bvalue\s+python:[^;\"]*?\bor\s+'([^']+)'", text):
            bad.append("{0}: value ... or '{1}'".format(name, m.group(1)))
    assert not bad, "a default rendered as a field value is saved as a choice: {0}".format(bad)


def test_scripts_never_write_defaults_into_fields():
    bad = []
    for d in (STATIC, TEMPLATES):
        for name in sorted(os.listdir(d)):
            if not name.endswith((".js", ".pt")):
                continue
            with open(os.path.join(d, name)) as fh:
                for i, line in enumerate(fh, 1):
                    if re.search(r"\.value\s*=\s*[^;=]*\b(\w+_default|defaults|derived\w*)\b", line, re.I):
                        bad.append("{0}:{1}".format(name, i))
    assert not bad, "script writes a derived default into a field: {0}".format(bad)


def test_bad_numbers_are_refused_not_coerced():
    bad = []
    for name, src, tree in _py():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body = ast.get_source_segment(src, node.body[0]) or ""
            if "float(" not in body and "int(" not in body:
                continue
            for h in node.handlers:
                if "ValueError" not in (ast.get_source_segment(src, h.type) or ""):
                    continue
                for st in h.body:
                    if isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant) \
                            and st.value.value is not None:
                        target = ast.get_source_segment(src, st.targets[0])
                        if (name, target) not in COERCION_ALLOWED:
                            bad.append("{0}:{1} {2} = {3!r}".format(
                                name, st.lineno, target, st.value.value))
    assert not bad, "unparseable input silently replaced by a default: {0}".format(bad)


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
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
