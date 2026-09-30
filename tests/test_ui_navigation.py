# -*- coding: utf-8 -*-
"""Navigation: one table decides each role's landing (GAPS §49, Phase 3).

The launcher (@@pfas-home) redirected by its own if/elif chain, and nothing in
the sidebar led to a role's landing at all -- the only way in was a dashboard
tile. Now `workspace_home.LANDINGS` / `landing_for()` is the single source:
the launcher redirects with it and the sidebar pins it, so they cannot
disagree. Bench Chemist = LabClerk (decided 2026-09-30).

The real landing_for() is exercised, extracted from source (the module needs
Zope to import).
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.path.join(ROOT, "src", "senaite", "pfas", "browser")
HOME = os.path.join(BROWSER, "workspace_home.py")
SIDEBAR_PT = os.path.join(BROWSER, "templates", "pfas_sidebar.pt")
MACROS_PT = os.path.join(BROWSER, "templates", "pfas_macros.pt")


def _tree(path):
    with open(path) as fh:
        return ast.parse(fh.read())


def _landing_for():
    tree = _tree(HOME)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") in ("LANDINGS", "DEFAULT_LANDING") for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "landing_for")]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), HOME, "exec"), ns)
    return ns["landing_for"]


def test_each_role_lands_where_claude_md_says():
    f = _landing_for()
    assert f(["LabManager"])["view"] == "@@pfas-qc-management"
    assert f(["Manager"])["view"] == "@@pfas-qc-management"
    assert f(["Analyst"])["view"] == "@@pfas-data-review-home"
    assert f(["Verifier"])["view"] == "@@pfas-data-review-home"
    assert f(["LabClerk"])["view"] == "@@pfas-bench"
    assert f(["Client"])["view"] == "@@pfas-track"
    assert f(["Authenticated"])["view"] == "@@pfas-sample-status"


def test_precedence_manager_over_analyst_over_clerk():
    f = _landing_for()
    assert f(["LabClerk", "Analyst", "LabManager"])["view"] == "@@pfas-qc-management"
    assert f(["LabClerk", "Analyst"])["view"] == "@@pfas-data-review-home"


def test_role_group_is_a_real_sidebar_group():
    f = _landing_for()
    with open(SIDEBAR_PT) as fh:
        groups = set(re.findall(r'class="pfas-sg" id="([\w-]+)"', fh.read()))
    for roles in (["LabManager"], ["Analyst"], ["LabClerk"], ["Authenticated"]):
        g = f(roles)["group"]
        assert g in groups, "{0} opens {1!r}, which is not a sidebar group".format(roles, g)


def test_launcher_has_no_private_routing():
    tree = _tree(HOME)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "PFASWorkspaceHomeView":
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            strs = {n.value for n in ast.walk(node) if isinstance(n, ast.Constant)
                    and isinstance(n.value, str)}
            assert "landing_for" in names, "launcher does not use landing_for"
            assert not strs & {"LabManager", "Analyst", "Verifier", "LabClerk"}, (
                "launcher compares role names itself")
            return
    raise AssertionError("PFASWorkspaceHomeView not found")


def test_sidebar_pins_the_landing_and_opens_the_role_group():
    with open(SIDEBAR_PT) as fh:
        pt = fh.read()
    assert "home    view/landing" in pt, "sidebar does not read view/landing"
    assert 'href home/url' in pt, "no pinned link to the landing"
    assert 'data-role-group home/group' in pt, "role group not exposed to the script"
    assert "getAttribute('data-role-group')" in pt, "script ignores the role group"


def test_breadcrumb_comes_from_the_sidebar():
    with open(MACROS_PT) as fh:
        pt = fh.read()
    assert 'id="pfas-crumb"' in pt
    assert ".pfas-sidebar .pfas-si.si-active" in pt, "breadcrumb not derived from the nav"


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
