# -*- coding: utf-8 -*-
"""Issued method profile revisions and the badge rule (DECISIONS 2026-10-02).

Revisions: numbering, "unissued changes" detection (a save stamp is not a
change; a setting or a rule switch is), and a frozen PDF is never
overwritten. Badges: the always-true labels removed in the sweep stay gone,
and the shared table macro only makes a tag of a warning. No Zope.
"""
from __future__ import unicode_literals

import io
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
TPL = os.path.join(PKG, "browser", "templates")
sys.path.insert(0, PKG)

import method_revisions as mr       # noqa: E402

PROFILE = {"method_id": "EPA_537_1", "qc_acceptance": {"Dup": {"tiers": [{"rpd_max": 30.0}]}},
           "updated_at": "2026-10-01T10:00", "updated_by": "admin"}


def test_numbering_and_status():
    assert mr.next_number([]) == 1
    assert mr.next_number([{"rev": 1}, {"rev": 3}]) == 4
    st = mr.status([], "x")
    assert st["rev"] is None and st["unissued"] is True
    recs = [{"rev": 1, "fingerprint": "a", "issued_at": "d1", "issued_by": "u"},
            {"rev": 2, "fingerprint": "b", "issued_at": "d2", "issued_by": "u"}]
    assert mr.status(recs, "b") == {"rev": 2, "issued_at": "d2", "issued_by": "u", "unissued": False}
    assert mr.status(recs, "a")["unissued"] is True          # compared with the LATEST revision


def test_a_save_stamp_is_not_a_change_but_a_setting_or_switch_is():
    import copy
    base = mr.fingerprint(PROFILE, {"cal_r2": True})
    resaved = dict(PROFILE, updated_at="2026-10-02T09:00", updated_by="someone")
    assert mr.fingerprint(resaved, {"cal_r2": True}) == base
    changed = copy.deepcopy(PROFILE)
    changed["qc_acceptance"]["Dup"]["tiers"][0]["rpd_max"] = 25.0
    assert mr.fingerprint(changed, {"cal_r2": True}) != base
    assert mr.fingerprint(PROFILE, {"cal_r2": False}) != base


def test_issue_writes_the_pdf_and_never_overwrites_it():
    store, tmp = {}, tempfile.mkdtemp()
    old_ann, old_env = mr._ann, os.environ.get("PFAS_PROFILES_PATH")
    mr._ann = lambda portal: store
    os.environ["PFAS_PROFILES_PATH"] = os.path.join(tmp, "method_profiles.json")
    try:
        r1 = mr.issue(None, "EPA_537_1", b"%PDF-1 one", "fp1", "admin", "2026-10-02 10:00", "first")
        r2 = mr.issue(None, "EPA_537_1", b"%PDF-1 two", "fp2", "admin", "2026-10-02 11:00", "")
        assert (r1["rev"], r2["rev"]) == (1, 2)
        assert mr.read_pdf("EPA_537_1", 1) == b"%PDF-1 one" and mr.read_pdf("EPA_537_1", 2) == b"%PDF-1 two"
        assert [r["rev"] for r in mr.records(None, "EPA_537_1")] == [1, 2]
        try:
            mr.issue(None, "EPA_537_1", b"x", "fp3", "admin", "now", "", rev=2)
            assert False, "overwrote an issued revision"
        except ValueError:
            pass
        assert mr.read_pdf("EPA_537_1", 2) == b"%PDF-1 two"
        assert len(mr.records(None, "EPA_537_1")) == 2           # no record for the refused one
    finally:
        mr._ann = old_ann
        if old_env is None:
            os.environ.pop("PFAS_PROFILES_PATH", None)
        else:
            os.environ["PFAS_PROFILES_PATH"] = old_env
        shutil.rmtree(tmp)


def _templates():
    for name in sorted(os.listdir(TPL)):
        if name.endswith(".pt"):
            with io.open(os.path.join(TPL, name), encoding="utf-8") as fh:
                yield name, fh.read()


def test_always_true_labels_stay_gone():
    banned = [r'<span class="role-badge">LabManager</span>', r'>\s*Customised\s*</span>',
              r'>\s*limits set\s*</span>', r'badge badge-method']
    for name, text in _templates():
        for pat in banned:
            assert not re.search(pat, text), (name, pat)
    with io.open(os.path.join(PKG, "method_profile_sections.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert '"core type"' not in src and '"note": u"method default"' not in src


def test_the_table_macro_only_tags_a_warning():
    with io.open(os.path.join(TPL, "config_form_macros.pt"), encoding="utf-8") as fh:
        macro = fh.read()
    tag = re.search(r'<span tal:condition="python:row\[\'note\'\] and row\[\'warn\'\]" class="sur-tag', macro)
    plain = re.search(r'<span tal:condition="python:row\[\'note\'\] and not row\[\'warn\'\]" class="cf-hint"', macro)
    assert tag and plain
    assert "sur-tag sur-core" not in macro


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
