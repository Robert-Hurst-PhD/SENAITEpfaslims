# -*- coding: utf-8 -*-
"""The Lab Settings console: lists everything, owns nothing.

The console's value depends on three properties that are easy to lose later, and
each has a concrete precedent in this codebase:

  1. **It must not write.** Every setting declared so far is owned by an existing
     editor (Rule 2). A console that also wrote them would create a second owner
     for one fact — the defect shape WIRING.md §1.4 reports and §33.9 already paid
     for, when three separate resolvers gave three different answers about whether
     one parent existed.
  2. **Its "Edit in …" links must resolve.** A console that sends an admin to a
     view that is not registered is worse than no console: they conclude the
     setting cannot be changed. This is the §41.4 defect in a new place — a link
     that was never reachable because nothing checked it.
  3. **No declared setting may be registry-owned until something reads it.**
     `profiles/default/registry.xml` ships four `senaite.pfas.*` records that
     nothing reads; they appear editable in Plone's control panel and change
     nothing. The registry must not reproduce that.

Static/AST rather than imported: `settings_adapters` imports
`senaite.pfas.settings_registry` as a package, which the Py3 test interpreter
cannot resolve, and its hooks reach into stores that need Zope. Parsing the
declarations is both sufficient and stable.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "senaite", "pfas")
ADAPTERS = os.path.join(SRC, "settings_adapters.py")
VIEW = os.path.join(SRC, "browser", "lab_settings.py")
TEMPLATE = os.path.join(SRC, "browser", "templates", "lab_settings.pt")
MACROS = os.path.join(SRC, "browser", "templates", "pfas_macros.pt")
ZCML = os.path.join(SRC, "browser", "configure.zcml")
REGISTRY = os.path.join(SRC, "settings_registry.py")
SIDEBAR = os.path.join(SRC, "browser", "templates", "pfas_sidebar.pt")


def _read(path):
    with open(path) as fh:
        return fh.read()


def _strip_comments(body):
    """Blank HTML and CSS comments, preserving line numbering.

    Necessary, not fastidious. The FIFTH occurrence of this trap in this
    codebase: the comment written in lab_settings.pt to explain WHICH badge
    colours are global names `.badge-custom`, and a raw scan for a page-local
    redefinition matched the prose describing the promotion. The earlier four are
    recorded in tests/test_rule_toggles.py, the ISO-date test, and GAPS §40.1 and
    §41.6. Prose about a name contains the name; strip prose, scan markup.
    """
    def _blank(match):
        return re.sub(r"[^\n]", " ", match.group(0))
    body = re.sub(r"<!--.*?-->", _blank, body, flags=re.S)
    return re.sub(r"/\*.*?\*/", _blank, body, flags=re.S)


def _link_calls():
    """Every `_link(...)` declaration in settings_adapters, as (args, keywords)."""
    tree = ast.parse(_read(ADAPTERS))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_link"):
            out.append(node)
    return out


def _const(node):
    if isinstance(node, ast.Constant):
        return node.value
    return None


# ── 1. The console lists; it does not write ─────────────────────────────────

def test_the_console_view_never_writes_a_setting():
    body = _read(VIEW)
    for forbidden in ("set_value(", "save_facility_defaults", "save_library",
                      "save_print_settings", "_save"):
        assert forbidden not in body, (
            "the console calls %r — it must link to the owning editor, not "
            "become a second writer for the same fact" % forbidden)


def test_the_console_view_has_no_post_handler():
    """Not merely "does not write today": it must have no branch that could."""
    body = _read(VIEW)
    assert "request.method" not in body, (
        "the console has a request-method branch; in this phase it is read-only "
        "and a POST path is how that quietly stops being true")


def test_the_console_reads_through_the_registry_not_the_stores():
    """One read path per fact. Reaching into facility_qc here would duplicate
    what the declared describe_hook already does."""
    body = _read(VIEW)
    assert "describe_all" in body
    for direct in ("from senaite.pfas import facility_qc",
                   "from senaite.pfas import print_settings",
                   "qc_qualification"):
        assert direct not in body, (
            "the console imports %r directly instead of going through the "
            "registry's declared hook" % direct)


# ── 2. Every "Edit in …" link resolves ──────────────────────────────────────

def test_every_declared_owner_view_is_actually_registered():
    """An admin sent to an unregistered view concludes the setting cannot be
    changed. Cheap to check, and nothing else checks it."""
    zcml = _read(ZCML)
    registered = set(re.findall(r'name="([^"]+)"', zcml))
    missing = []
    for call in _link_calls():
        # _link(key, label, group, kind, hook, owner_view, **kw)
        if len(call.args) >= 6:
            owner = _const(call.args[5])
            if owner and owner.lstrip("@") not in registered:
                missing.append(owner)
    assert not missing, (
        "these owner views are declared but not registered in configure.zcml, so "
        "their 'Edit in' link goes nowhere: %s" % sorted(set(missing)))


def test_every_declaration_names_an_owner_view():
    """A setting with no owner would render "this page" — which is a lie while the
    console is read-only."""
    anonymous = []
    for call in _link_calls():
        owner = _const(call.args[5]) if len(call.args) >= 6 else None
        if not owner:
            key = _const(call.args[0]) if call.args else "?"
            anonymous.append(key)
    assert not anonymous, "declared with no owning view: %s" % anonymous


# ── 3. No registry-owned key without a consumer ─────────────────────────────

def test_nothing_is_declared_registry_owned_yet():
    """A registry-owned setting is created only together with the code that reads
    it. Otherwise the console lists a setting that changes nothing — exactly what
    registry.xml's four dead records do."""
    body = _read(ADAPTERS)
    assert "STORAGE_REGISTRY" not in body, (
        "settings_adapters declares a registry-owned setting; that may only "
        "happen in the same change as the consumer that reads it")


def test_every_declaration_names_the_accessor_it_reads_through():
    """`reader=` is what lets the audit resolve an accessor edge. A key-literal
    grep cannot see `get_library(portal)` — which is why WIRING.md needs its
    "reached through an accessor" section at all."""
    missing = []
    for call in _link_calls():
        readers = [kw for kw in call.keywords if kw.arg == "reader"]
        if not readers:
            key = _const(call.args[0]) if call.args else "?"
            missing.append(key)
    assert not missing, (
        "declared without a reader, so the audit cannot tell whether anything "
        "consumes them: %s" % missing)


# ── The status column ───────────────────────────────────────────────────────

def test_the_status_column_covers_every_source_the_registry_can_emit():
    """A source the console does not know about renders as "Unknown", which reads
    as a broken store rather than a new state. Sources are enumerated from the
    registry so adding one there fails here."""
    view = _read(VIEW)
    meta = re.search(r"_STATUS_META\s*=\s*\{(.*?)\n\}", view, re.S).group(1)
    known = set(re.findall(r'"(\w+)":', meta))
    registry = _read(REGISTRY)
    # Every literal source string the registry assigns.
    emitted = set(re.findall(r'source["\']?\s*[:=]\s*["\'](\w+)["\']', registry))
    emitted |= set(re.findall(r'source=["\'](\w+)["\']', registry))
    missing = emitted - known
    assert not missing, (
        "the registry can report source=%s and the console has no badge for it, "
        "so it would render as Unknown" % sorted(missing))


def test_the_badge_colours_live_in_the_shared_macros_not_this_page():
    """§6C: define UI once. These two were page-local in method_profiles.pt until
    a second page needed them."""
    macros = _read(MACROS)
    page = _strip_comments(_read(TEMPLATE))
    view = _strip_comments(_read(VIEW))
    used = set(re.findall(r'"(badge-[\w-]+)"', view))
    assert used, "the console defines no status badges at all"
    for cls in sorted(used):
        assert ".%s" % cls in macros, (
            "%s is used by the console but not defined in pfas_macros.pt" % cls)
        assert ".%s " % cls not in page and ".%s{" % cls not in page, (
            "%s is redefined page-locally; it is global now" % cls)
    profiles = _strip_comments(_read(os.path.join(
        SRC, "browser", "templates", "method_profiles.pt")))
    assert ".badge-custom  {" not in profiles, (
        "method_profiles.pt still carries the page-local copy that was promoted")


# ── Reachability ────────────────────────────────────────────────────────────

def test_the_console_is_registered_and_gated():
    zcml = _read(ZCML)
    block = zcml.split('name="pfas-lab-settings"', 1)[1].split("/>", 1)[0]
    assert "permission=" in block, "the console is registered with no permission"
    assert "zope2.View" not in block, (
        "the console is registered at zope2.View, i.e. any authenticated user")


def test_the_console_is_reachable_from_the_sidebar():
    """The two orphaned config pages (@@pfas-qc-type-grid reachable from nowhere)
    are why this is worth asserting."""
    sidebar = _read(SIDEBAR)
    assert "@@pfas-lab-settings" in sidebar, (
        "the console is not linked from the sidebar, so it is reachable only by "
        "typing the URL — the state @@pfas-qc-type-grid is in")
    # In the Configuration group, which is the manager-gated one.
    after = sidebar.split("CONFIGURATION", 1)
    assert len(after) == 2 and "@@pfas-lab-settings" in after[1], (
        "the console link is outside the Configuration group")


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
