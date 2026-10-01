# -*- coding: utf-8 -*-
"""A sample's method, for the certificate and the publish guard
(DECISIONS 2026-10-02). Fakes stand in for analyses and SENAITE."""
from __future__ import unicode_literals

import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import sample_method as sm      # noqa: E402


class _M(object):
    def __init__(self, mid):
        self.mid = mid

    def UID(self):
        return "uid-" + self.mid

    def getMethodID(self):
        return self.mid


class _A(object):
    portal_type = "Analysis"

    def __init__(self, method, hidden=False, state="verified"):
        self._m, self._h, self.review_state = method, hidden, state

    def getMethod(self):
        return self._m

    def getHidden(self):
        return self._h


FDA, EPA = _M("FDA_32PFAS"), _M("EPA_537_1")


def test_one_method_is_identified():
    m, problem = sm.identify_from([_A(FDA), _A(FDA)])
    assert m is FDA and problem == ""


def test_no_method_mixed_methods_or_partly_missing_are_refused_with_the_remedy():
    for analyses, words in (([_A(None), _A(None)], "none of this sample's analyses"),
                            ([_A(FDA), _A(EPA)], "different methods (EPA_537_1, FDA_32PFAS)"),
                            ([_A(FDA), _A(None)], "1 of this sample's analyses have no method")):
        m, problem = sm.identify_from(analyses)
        assert m is None and words in problem and sm.REMEDY in problem, (words, problem)


def test_nothing_to_report_is_not_refused():
    assert sm.identify_from([]) == (None, "")


def test_unreported_analyses_do_not_count():
    class _S(object):
        def objectValues(self):
            return [_A(FDA), _A(None, hidden=True), _A(EPA, state="retracted"), object()]
    m, problem = sm.identify(_S())
    assert m is FDA and problem == ""


def _guard_module():
    """guards.py with fake bika / zope pieces."""
    saved = dict((k, sys.modules.get(k)) for k in
                 ("bika", "bika.lims", "bika.lims.interfaces", "zope", "zope.interface"))
    bika, lims, ifaces = (types.ModuleType(str(n)) for n in ("bika", "bika.lims", "bika.lims.interfaces"))
    ifaces.IGuardAdapter = object
    lims.interfaces, bika.lims = ifaces, lims
    zope_mod, zi = types.ModuleType(str("zope")), types.ModuleType(str("zope.interface"))
    zi.implementer = lambda *a: (lambda cls: cls)
    zope_mod.interface = zi
    sys.modules.update({"bika": bika, "bika.lims": lims, "bika.lims.interfaces": ifaces,
                        "zope": zope_mod, "zope.interface": zi})
    sys.path.insert(0, os.path.join(PKG, "browser"))
    try:
        import importlib
        if "guards" in sys.modules:
            del sys.modules["guards"]
        mod = importlib.import_module("guards")
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mod


def test_the_guard_blocks_only_publishing_and_fails_closed():
    g = _guard_module()
    old = sm.identify
    pkg = types.ModuleType(str("senaite.pfas"))
    pkg.sample_method = sm
    saved = dict((k, sys.modules.get(k)) for k in ("senaite", "senaite.pfas", "senaite.pfas.sample_method"))
    sys.modules.update({"senaite": types.ModuleType(str("senaite")), "senaite.pfas": pkg,
                        "senaite.pfas.sample_method": sm})
    try:
        sm.identify = lambda sample: (None, "Method not identified")
        guard = g.SampleMethodGuard(object())
        assert [guard.guard(t) for t in ("publish", "prepublish", "republish")] == [False] * 3
        assert guard.guard("verify") is True and guard.guard("submit") is True
        sm.identify = lambda sample: (FDA, "")
        assert guard.guard("publish") is True

        def boom(sample):
            raise RuntimeError("catalog down")
        sm.identify = boom
        assert guard.guard("publish") is False                  # an error never allows it
    finally:
        sm.identify = old
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_registered_and_used_by_the_certificate():
    with io.open(os.path.join(PKG, "browser", "configure.zcml"), encoding="utf-8") as fh:
        zcml = fh.read()
    assert 'factory=".guards.SampleMethodGuard"' in zcml and 'name="senaite.pfas.sample_method"' in zcml
    with io.open(os.path.join(PKG, "browser", "coa_sections.py"), encoding="utf-8") as fh:
        src = fh.read()
    body = src[src.index("    def _sample("):]
    assert body.index("identify_from(analyses)") < body.index("get_profile(")
    assert '"error": problem' in body


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
