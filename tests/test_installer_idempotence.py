# -*- coding: utf-8 -*-
"""The installer runs on every restart, so it may only fill what is missing.

GAPS §47. The SENAITE container's entrypoint runs `buildout -c custom.cfg`
on every start, and custom.cfg enables collective.recipe.plonesite with
`senaite.pfas:default` -- so the profile, setup_handler and post_install
re-run each time. portal_setup held 325 import logs for this profile. Every
seed value written to an EXISTING object was therefore a silent revert of the
lab's edit, proven live: a Method description tagged in setup came back as the
CSV text after one restart.

Pinned here, statically (the installer needs Zope):

  1. In setup_handler, no `set*` call on a get-or-created object runs outside
     an `if created:` guard.
  2. create_reference_definitions does not unpack QC_REF_SPEC's rows into the
     wrong arity (it raised on every restart and was swallowed), and it skips
     an existing definition.
  3. seed_builtin_logbook_defs touches nothing on an existing definition that
     the editor's form exposes.
  4. The logbook editor does not read `builtin` from the form, which does not
     send it -- every save cleared the flag and only the restart put it back.
  5. (GAPS §48) Methods, services and sample types are matched on their stable
     key (MethodID / Keyword / Prefix) before Title, so a renamed seed is found
     rather than re-seeded; a Title match carrying a DIFFERENT key is never
     adopted. Exercised on the real function against a fake container.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "senaite", "pfas")
SETUP = os.path.join(SRC, "setuphandlers.py")
PREP = os.path.join(SRC, "browser", "prep_logbooks.py")
SETUPREFS = os.path.join(SRC, "browser", "setuprefs.py")
PREP_TEMPLATE = os.path.join(SRC, "browser", "templates", "prep_logbooks.pt")


def _tree(path):
    with open(path) as fh:
        return ast.parse(fh.read())


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("{0} not found".format(name))


def _parents(root):
    out = {}
    for node in ast.walk(root):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _under_created_guard(node, parents):
    cur = node
    while cur in parents:
        parent = parents[cur]
        if (isinstance(parent, ast.If) and cur in parent.body
                and isinstance(parent.test, ast.Name)
                and parent.test.id == "created"):
            return True
        cur = parent
    return False


def _get_or_created_names(func):
    """Names bound from `x, created = _get_or_create(...)`."""
    names = set()
    for node in ast.walk(func):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_get_or_create"):
            tgt = node.targets[0]
            if isinstance(tgt, ast.Tuple) and isinstance(tgt.elts[0], ast.Name):
                names.add(tgt.elts[0].id)
            elif isinstance(tgt, ast.Name):
                names.add(tgt.id)
            elif isinstance(tgt, ast.Subscript):
                pass
    return names


def test_seed_setters_only_touch_objects_just_created():
    func = _func(_tree(SETUP), "setup_handler")
    parents = _parents(func)
    seeded = _get_or_created_names(func)
    assert {"m", "svc", "st"} <= seeded, seeded
    offenders = []
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("set")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in seeded
                and not _under_created_guard(node, parents)):
            offenders.append("{0}.{1} line {2}".format(
                node.func.value.id, node.func.attr, node.lineno))
    assert not offenders, "seed written to existing objects: {0}".format(offenders)


def test_get_or_create_reports_whether_it_created():
    func = _func(_tree(SETUP), "_get_or_create")
    nested = set()
    for n in ast.walk(func):
        if isinstance(n, ast.FunctionDef) and n is not func:
            nested.update(ast.walk(n))
    returns = [n for n in ast.walk(func)
               if isinstance(n, ast.Return) and n not in nested]
    assert returns and all(isinstance(r.value, ast.Tuple) and len(r.value.elts) == 2
                           for r in returns), "must return (obj, created)"


def _spec_arity():
    for node in _tree(SETUPREFS).body:
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "QC_REF_SPEC"):
            sizes = {len(v.elts) for v in node.value.values}
            assert len(sizes) == 1, sizes
            return sizes.pop()
    raise AssertionError("QC_REF_SPEC not found")


def test_reference_definitions_unpack_matches_spec_and_skip_existing():
    func = _func(_tree(SETUP), "create_reference_definitions")
    arity = _spec_arity()
    loops = [n for n in ast.walk(func) if isinstance(n, ast.For)
             and "QC_REF_SPEC" in ast.dump(n.iter)]
    assert len(loops) == 1, len(loops)
    tgt = loops[0].target
    # (code, spec) or (code, (a, b, c, d, e)) -- never a wrong-arity inner tuple.
    assert isinstance(tgt, ast.Tuple) and len(tgt.elts) == 2
    inner = tgt.elts[1]
    if isinstance(inner, ast.Tuple):
        assert len(inner.elts) == arity, (len(inner.elts), arity)
    dump = ast.dump(loops[0])
    assert "is_new" in dump and "Continue" in dump, (
        "an existing Reference Definition must be skipped")


def _form_field_names():
    import re
    with open(PREP_TEMPLATE) as fh:
        body = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    return set(re.findall(r'name="([a-z_]+)"', body))


def test_builtin_logbook_seeder_leaves_editor_fields_alone():
    func = _func(_tree(PREP), "seed_builtin_logbook_defs")
    # The `if existing is not None:` branch.
    branch = None
    for node in ast.walk(func):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and getattr(node.test.left, "id", "") == "existing"):
            branch = node
    assert branch is not None
    written = set()
    for node in ast.walk(branch):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setattr":
            written.add("<dynamic setattr>")
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and getattr(t.value, "id", "") == "existing":
                    written.add(t.attr)
    editable = _form_field_names()
    assert "<dynamic setattr>" not in written, "seeder writes fields dynamically"
    clobbered = (written & editable) - {"field_schema_json"}
    assert not clobbered, "seeder overwrites editor fields: {0}".format(clobbered)
    assert {"sort_order", "active", "logbook_code", "method_slug"} <= editable


def test_editor_does_not_read_builtin_from_the_form():
    assert "builtin" not in _form_field_names()
    func = _func(_tree(PREP), "_handle_upsert")
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "builtin"
                and getattr(node.func.value, "id", "") == "f"):
            raise AssertionError("builtin read from the form at line {0}".format(
                node.lineno))


# ── 5. Stable-key matching (GAPS §48) ──────────────────────────────────────

KEYED_CALLS = {"Method": "getMethodID", "AnalysisService": "getKeyword",
               "SampleType": "getPrefix"}


def test_keyed_types_pass_their_stable_key():
    func = _func(_tree(SETUP), "setup_handler")
    seen = {}
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_get_or_create" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)):
            continue
        ptype = node.args[1].value
        if ptype not in KEYED_CALLS:
            continue
        kws = {k.arg: k.value for k in node.keywords}
        key = kws.get("key")
        assert isinstance(key, ast.Tuple) and isinstance(key.elts[0], ast.Constant), \
            "{0} call at line {1} passes no key".format(ptype, node.lineno)
        assert key.elts[0].value == KEYED_CALLS[ptype], \
            "{0} keyed on {1}".format(ptype, key.elts[0].value)
        seen[ptype] = seen.get(ptype, 0) + 1
    assert seen == {"Method": 1, "AnalysisService": 2, "SampleType": 1}, seen


class _Obj(object):
    def __init__(self, title, **keys):
        self._title = title
        self._keys = keys

    def Title(self):
        return self._title

    def __getattr__(self, name):
        if name.startswith("get"):
            return lambda: self.__dict__["_keys"].get(name, "")
        raise AttributeError(name)


class _Folder(object):
    def __init__(self, *objs):
        self.objs = list(objs)

    def objectValues(self):
        return list(self.objs)


def _load_get_or_create():
    """The real _get_or_create, with bika.lims.api replaced by a stub."""
    import logging
    import types
    tree = _tree(SETUP)
    fn = _func(tree, "_get_or_create")
    mod = ast.Module(body=[fn], type_ignores=[])
    api = types.ModuleType("bika.lims.api")

    def create(container, ptype, title=None, **kw):
        obj = _Obj(title)
        container.objs.append(obj)
        return obj
    api.create = create
    lims = types.ModuleType("bika.lims")
    lims.api = api
    bika = types.ModuleType("bika")
    bika.lims = lims
    saved = {k: sys.modules.get(k) for k in ("bika", "bika.lims", "bika.lims.api")}
    sys.modules.update({"bika": bika, "bika.lims": lims, "bika.lims.api": api})
    ns = {"logger": logging.getLogger("t")}
    exec(compile(mod, SETUP, "exec"), ns)
    return ns["_get_or_create"], saved


def _with_goc(check):
    goc, saved = _load_get_or_create()
    try:
        check(goc)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_renamed_seed_is_found_by_key_not_reseeded():
    def check(goc):
        renamed = _Obj("Drinking Water (lab name)", getPrefix="DW")
        folder = _Folder(renamed)
        obj, created = goc(folder, "SampleType", "Drinking Water",
                           key=("getPrefix", "DW"))
        assert obj is renamed and not created
        assert len(folder.objs) == 1
    _with_goc(check)


def test_key_beats_title():
    def check(goc):
        by_title = _Obj("Soil", getPrefix="")
        by_key = _Obj("Soil (renamed)", getPrefix="SOIL")
        obj, created = goc(_Folder(by_title, by_key), "SampleType", "Soil",
                           key=("getPrefix", "SOIL"))
        assert obj is by_key and not created
    _with_goc(check)


def test_title_match_with_other_key_is_not_adopted():
    def check(goc):
        other = _Obj("PFOA", getKeyword="PFOA_LAB")
        folder = _Folder(other)
        obj, created = goc(folder, "AnalysisService", "PFOA",
                           key=("getKeyword", "PFOA"))
        assert created and obj is not other
    _with_goc(check)


def test_title_fallback_when_key_unset():
    def check(goc):
        unkeyed = _Obj("EPA 537.1", getMethodID="")
        obj, created = goc(_Folder(unkeyed), "Method", "EPA 537.1",
                           key=("getMethodID", "EPA_537_1"))
        assert obj is unkeyed and not created
    _with_goc(check)


def test_shared_key_prefers_matching_title():
    def check(goc):
        a = _Obj("Lab copy", getPrefix="MILK")
        b = _Obj("Milk", getPrefix="MILK")
        obj, _ = goc(_Folder(a, b), "SampleType", "Milk",
                     key=("getPrefix", "MILK"))
        assert obj is b
    _with_goc(check)


def test_unkeyed_types_stay_on_title():
    def check(goc):
        cat = _Obj("PFAS")
        obj, created = goc(_Folder(cat), "AnalysisCategory", "PFAS")
        assert obj is cat and not created
    _with_goc(check)


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
