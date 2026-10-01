# -*- coding: utf-8 -*-
"""Readers of a batch's criteria see what the batch runs to (GAPS §76).

project_specs.profile_for_batch: the method profile, plus the batch's project
specs when there are any -- the same effective profile the pipeline applied.
And the reverse guard: no function that SAVES a method profile may read the
project version, or a project's specs would be written into the method.
Fakes stand in for the Zope pieces (method store, project link, annotation).
"""
from __future__ import unicode_literals

import ast
import copy
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import project_specs as ps      # noqa: E402

METHOD = {"method_id": "EPA_537_1", "supported_matrices": ["Drinking Water", "Groundwater"],
          "qc_acceptance": {"Dup": {"enabled": True, "tiers": [{"name": "default", "rpd_max": 30.0}]}}}
SPECS = {"EPA_537_1": {"*": {"dup": {"changed": {"default": {"rpd_max": 25.0}}}},
                       "Groundwater": {"dup": {"changed": {"default": {"rpd_max": 35.0}}}}}}


def _fake_zope(project):
    """Install fake senaite.pfas.method_profile_store / project_ref modules."""
    pkg = types.ModuleType(str("senaite.pfas"))
    store = types.ModuleType(str("senaite.pfas.method_profile_store"))
    store.get_profile = lambda portal, mid: copy.deepcopy(METHOD) if mid == "EPA_537_1" else {}
    ref = types.ModuleType(str("senaite.pfas.project_ref"))
    ref.get_project = lambda portal, batch: project if batch == "B-LINKED" else None
    pkg.method_profile_store, pkg.project_ref = store, ref     # Py2 imports submodules as attributes
    saved = dict((k, sys.modules.get(k)) for k in
                 ("senaite", "senaite.pfas", "senaite.pfas.method_profile_store", "senaite.pfas.project_ref"))
    sys.modules.update({"senaite": types.ModuleType(str("senaite")), "senaite.pfas": pkg,
                        "senaite.pfas.method_profile_store": store, "senaite.pfas.project_ref": ref})
    return saved


def _restore(saved):
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _rpd(profile):
    return profile["qc_acceptance"]["Dup"]["tiers"][0]["rpd_max"]


def test_a_linked_batch_reads_its_project_specs_and_others_the_method():
    saved = _fake_zope(project="P1")
    old_get, old_env = ps.get_specs, ps.site_env
    ps.get_specs = lambda project: SPECS if project == "P1" else {}
    ps.site_env = lambda: {"services": {}}
    try:
        assert _rpd(ps.profile_for_batch(None, None, "EPA_537_1")) == 30.0            # no batch
        assert _rpd(ps.profile_for_batch(None, "B-OTHER", "EPA_537_1")) == 30.0       # no project
        assert _rpd(ps.profile_for_batch(None, "B-LINKED", "EPA_537_1", "Drinking Water")) == 25.0
        assert _rpd(ps.profile_for_batch(None, "B-LINKED", "EPA_537_1", "Groundwater")) == 35.0
        assert ps.profile_for_batch(None, "B-LINKED", "") == {}                       # no method
    finally:
        ps.get_specs, ps.site_env = old_get, old_env
        _restore(saved)


def test_the_readers_use_it():
    for rel in (("browser", "coa_sections.py"), ("browser", "data_review.py")):
        with io.open(os.path.join(PKG, *rel), encoding="utf-8") as fh:
            assert "profile_for_batch(" in fh.read(), rel
    with io.open(os.path.join(PKG, "browser", "data_review.py"), encoding="utf-8") as fh:
        src = fh.read()
    body = src[src.index("def _get_qc_summary"):]
    body = body[:body.index("\n    def ", 10)]
    assert "self._method_profile()" in body and "get_profile(" not in body


def test_no_method_writer_reads_the_project_version():
    """A function that calls save_profile must build on the METHOD profile."""
    for rel in (("browser", "data_review.py"), ("browser", "coa_sections.py"),
                ("browser", "method_profiles.py"), ("project_specs.py",)):
        path = os.path.join(PKG, *rel)
        with open(path, "rb") as fh:               # bytes: Py2 refuses a unicode source with a coding line
            tree = ast.parse(fh.read())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            calls = set(getattr(n.func, "id", getattr(n.func, "attr", None))
                        for n in ast.walk(fn) if isinstance(n, ast.Call))
            assert not ({"save_profile"} <= calls and calls & {"profile_for_batch", "_method_profile"}), (
                rel, fn.name)


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
