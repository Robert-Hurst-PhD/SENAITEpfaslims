# -*- coding: utf-8 -*-
"""Consolidation P4 (DECISIONS 2026-10-02): "no labelled standard" is
DERIVED per method from its surrogate links -- an analyte linked to its own
labelled analog has one; any other has none. Proven first: the derivation
reproduces the old global column on every shipped profile, so switching
changes no verdict today; and a link changed in one method moves the analyte
in that method only."""
from __future__ import unicode_literals

import copy
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)
sys.path.insert(0, ROOT)

import analyte_reference as ar          # noqa: E402
import labelled_coverage as lc          # noqa: E402
import qc_consolidation as qcc          # noqa: E402

ANALOG = ar.get_labeled_analog_map()
OLD_COLUMN = frozenset(r[0] for r in ar.NATIVE_ANALYTES if r[7])


def _profiles():
    path = os.environ.get("PFAS_PROFILES_PATH",
                          os.path.join(ROOT, "data", "qc", "method_profiles.json"))
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_derivation_reproduces_the_old_column_on_every_shipped_profile():
    for mid, p in sorted(_profiles().items()):
        if not p.get("surrogate_map"):
            continue
        panel = set(p.get("master_analyte_set") or [])
        assert lc.no_labelled_standard(p, ANALOG) == OLD_COLUMN & panel, mid


def test_a_link_change_moves_the_analyte_in_that_method_only():
    p = {"master_analyte_set": ["PFOA", "PFTrDA"],
         "surrogate_map": [{"analyte": "PFOA", "surrogate_is": "M8PFOA"},
                           {"analyte": "PFTrDA", "surrogate_is": "M2PFTeDA"}]}
    assert lc.no_labelled_standard(p, ANALOG) == frozenset(["PFTrDA"])
    q = copy.deepcopy(p)
    q["surrogate_map"][0]["surrogate_is"] = "M5PFHxA"           # PFOA quantified off another
    assert lc.no_labelled_standard(q, ANALOG) == frozenset(["PFOA", "PFTrDA"])
    r = copy.deepcopy(p)
    r["surrogate_map"] = r["surrogate_map"][:1]                # no link at all
    assert "PFTrDA" in lc.no_labelled_standard(r, ANALOG)
    assert lc.no_labelled_standard({"master_analyte_set": ["PFOA"],
                                    "surrogate_map": {"PFOA": "M8PFOA"}}, ANALOG) == frozenset()


def test_the_derived_flags_leave_per_analyte_rows():
    p = {"per_analyte": [{"analyte": "PFOA", "no_labeled_std": False, "is_key_analyte": True,
                          "recovery_tier": 1, "confirm_ion_mz": "413>169", "notes": "x"}]}
    assert qcc.drop_derived_per_analyte(p)
    assert p["per_analyte"] == [{"analyte": "PFOA", "confirm_ion_mz": "413>169", "notes": "x"}]
    assert not qcc.drop_derived_per_analyte(p)


def test_every_reader_uses_the_derivation():
    def src(*parts):
        with io.open(os.path.join(*parts), encoding="utf-8") as fh:
            return fh.read()
    pipe = src(ROOT, "pfas_pipeline", "method_profiles.py")
    assert pipe.count("no_labelled_names_for(") == 2 and "no_labeled_names()" not in pipe
    assert "def no_labeled_names" not in src(ROOT, "pfas_pipeline", "analyte_alias.py")
    for rel in (("project_specs.py",), ("spec_sync.py",), ("method_profile_sections.py",)):
        text = src(PKG, *rel)
        assert "no_std_set(" in text, rel
        assert "r[7]" not in text and "row[7]" not in text, rel
    assert "get_no_labeled" not in src(PKG, "analyte_reference.py")
    assert "no_labeled_std" not in src(PKG, "browser", "templates", "method_profile_edit.pt")


def test_the_worker_names_both_keywords_and_display_names():
    if sys.version_info[0] < 3:
        return
    from pfas_pipeline.analyte_alias import no_labelled_names_for
    p = {"master_analyte_set": ["9ClPF3ONS", "PFOA"],
         "surrogate_map": [{"analyte": "PFOA", "surrogate_is": "M8PFOA"}]}
    names = no_labelled_names_for(p)
    assert "9ClPF3ONS" in names and "9Cl-PF3ONS" in names and "PFOA" not in names


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
