# -*- coding: utf-8 -*-
"""The certificate's quality-system statement (DECISIONS 2026-10-01): the
lab's internal system, or the batch's project QAPP with its ACTIVE revision
-- never an invented one. Real modules, no Zope."""
from __future__ import unicode_literals

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(os.path.dirname(HERE), "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import qs_statement as qs      # noqa: E402

S = {qs.INTERNAL_KEY: qs.DEFAULT_INTERNAL, qs.QAPP_KEY: qs.DEFAULT_QAPP}
QAPP = {"id": "QAPP-007", "title": "Acme Farms PFAS monitoring", "rev": 3, "project": "ACME-1 Acme"}


def test_no_project_or_no_qapp_prints_the_internal_statement():
    assert qs.render(S, None) == qs.DEFAULT_INTERNAL
    assert qs.render(S, {"id": "", "title": "x"}) == qs.DEFAULT_INTERNAL


def test_a_qapp_fills_title_id_revision_and_project():
    text = qs.render(S, QAPP)
    for part in ("Acme Farms PFAS monitoring", "QAPP-007", "revision 3", "ACME-1 Acme"):
        assert part in text, (part, text)
    assert "{" not in text and "internal quality system" not in text


def test_no_active_revision_is_said_not_invented():
    text = qs.render(S, dict(QAPP, rev=None))
    assert qs.NO_REV in text and "revision None" not in text


def test_only_the_named_tokens_are_replaced():
    s = dict(S, **{qs.QAPP_KEY: "Plan {qapp_id} {other} {qapp_rev}"})
    assert qs.render(s, QAPP) == "Plan QAPP-007 {other} revision 3"


def test_the_defaults_use_every_token_and_reach_print_settings_and_the_certificate():
    for t in qs.TOKENS:
        assert "{%s}" % t in qs.DEFAULT_QAPP, t
    with io.open(os.path.join(PKG, "print_settings.py"), encoding="utf-8") as fh:
        ps = fh.read()
    assert '"coa_qs_internal": _qs.DEFAULT_INTERNAL' in ps and '"coa_qs_qapp": _qs.DEFAULT_QAPP' in ps
    with io.open(os.path.join(PKG, "browser", "templates", "coa_sections.pt"), encoding="utf-8") as fh:
        assert 'tal:content="smp/qs"' in fh.read()
    with io.open(os.path.join(PKG, "browser", "coa_sections.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert '"qs": self._quality_system(batch)' in src and "_project_source(portal, project)[1]" in src


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
