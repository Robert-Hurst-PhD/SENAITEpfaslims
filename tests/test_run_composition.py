# -*- coding: utf-8 -*-
"""Regression tests for senaite.pfas.run_composition -- the QC-COMPOSITION
transforms (duplicate_all_samples / lfsm_frequency) the LC-MS run builder
(senaite.pfas.browser.run_builder) applies inside its SAMPLES-token block.

run_builder.py itself cannot be imported here (it imports zope.annotation /
Products.CMFCore / Products.Five at module load, none of which are
installed outside the Plone container) -- which is exactly why this
transform lives in its own Zope-free module, loadable by path like
ruleset.py / method_baselines.py / holding_time.py. This file is the closest
available proof of "a project-less batch builds exactly the run it builds
today": compose_sample_block() is the ONLY place duplicate_all_samples /
lfsm_frequency change what gets injected, and its identity property on
None/falsy arguments is pinned here directly. The full integration (through
build_sequence(), the method profile, ruleset resolution and the actual
worklist CSV) was verified live against the running instance -- see the
task report for the before/after CSV diff on batch B-002.

    python3 tests/test_run_composition.py
"""
from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, os.pardir, "src", "senaite", "pfas")


def _load(path, name):
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except ImportError:
        import imp
        return imp.load_source(name, path)


rc = _load(os.path.join(_SRC, "run_composition.py"),
           "pfas_run_composition_under_test")


def _rows(*ids):
    return [{"sample_id": sid, "matrix": "Eggs", "client_sample_id": sid}
            for sid in ids]


# ── classify_sample_role / is_field_sample ───────────────────────────────────

def test_classify_sample_role_recognizes_qc_ids():
    # NOTE: the MB match is `"MB" in sid.split()` -- a literal, space-
    # separated "MB" token, not a substring -- copied verbatim from the
    # original run_builder._role_from_sample. A hyphenated id like
    # "FDA-MB-01" does NOT match (pre-existing behavior, out of scope for
    # this change); "Batch MB Blank" does.
    assert rc.classify_sample_role({"sample_id": "Batch MB Blank"}) == "MB"
    assert rc.classify_sample_role({"sample_id": "FDA-MB-01"}) == ""
    assert rc.classify_sample_role({"sample_id": "EGG-0001-LFSM"}) == "LFSM"
    assert rc.classify_sample_role({"sample_id": "EGG-0001-LFSMD"}) == "LFSMD"
    assert rc.classify_sample_role(
        {"sample_id": "LFSM Mid Duplicate"}) == "LFSMD", (
        "a duplicate written 'LFSM ... Duplicate' must still classify as "
        "LFSMD, not a plain LFSM")
    assert rc.classify_sample_role({"sample_id": "EGG-0001"}) == ""


def test_is_field_sample_true_only_for_unrouted_rows():
    assert rc.is_field_sample({"sample_id": "EGG-0001"}) is True
    assert rc.is_field_sample({"sample_id": "EGG-0001-LFSM"}) is False
    assert rc.is_field_sample({"sample_id": "EGG-0001", "role": "LFSM"}) is False
    assert rc.is_field_sample({"sample_id": "EGG-0001", "role": ""}) is True


def test_an_explicit_sample_role_is_still_a_field_sample():
    """Caught live against a real batch (B-002): run_builder.sample_rows()
    reads the extraction log's QC-role column into row["role"], and an
    ORDINARY field sample's value there is the literal string "Sample", not
    blank. Treating any non-empty role as disqualifying (the first cut of
    this module) meant duplicate_all_samples / lfsm_frequency silently
    applied to ZERO rows against real data, despite passing every test built
    against hand-written fixtures with role="" or no role key at all."""
    row = {"sample_id": "EGG-0001", "role": "Sample", "matrix": "Eggs"}
    assert rc.is_field_sample(row) is True
    out = rc.compose_sample_block([row], True, None)
    assert [m for _, m in out] == ["sample", "duplicate"], (
        "a role='Sample' row must still be duplicated under "
        "duplicate_all_samples")


def test_qc_role_values_are_recognized_case_insensitively():
    for role in ("MB", "mb", "LFSM", "Lfsmd", "Dup", "dup"):
        assert rc.is_field_sample({"sample_id": "X", "role": role}) is False, role


# ── compose_sample_block: the safety property ────────────────────────────────

def test_identity_when_both_overrides_are_none():
    """THE safety property: a project-less batch resolves both composition
    keys to None (senaite.pfas.ruleset rule 3), and that must build EXACTLY
    the sequence built before this module existed -- no duplicate rows, no
    extra LFSM markers, same order, same objects."""
    rows = _rows("EGG-0001", "EGG-0002", "MEAT-0001")
    out = rc.compose_sample_block(rows, None, None)
    assert out == [(r, "sample") for r in rows], out


def test_identity_when_both_overrides_are_falsy_defaults():
    rows = _rows("EGG-0001", "EGG-0002")
    assert rc.compose_sample_block(rows, False, 0) == \
        [(r, "sample") for r in rows]
    assert rc.compose_sample_block(rows, False, None) == \
        [(r, "sample") for r in rows]


# ── duplicate_all_samples ────────────────────────────────────────────────────

def test_duplicate_all_samples_doubles_every_field_sample():
    rows = _rows("EGG-0001", "EGG-0002")
    out = rc.compose_sample_block(rows, True, None)
    markers = [m for _, m in out]
    assert markers == ["sample", "duplicate", "sample", "duplicate"], markers
    dup = out[1][0]
    assert dup["sample_id"] == "EGG-0001"
    assert dup["is_duplicate"] is True
    assert dup is not rows[0], "the duplicate must be a copy, not the same row"


def test_duplicate_all_samples_never_doubles_a_registered_qc_row():
    """A registered LFSM/MB sample sitting in sample_rows is NOT a field
    sample -- "all samples run in duplicate" means field samples, not the
    batch's own QC injections."""
    rows = _rows("EGG-0001") + [{"sample_id": "EGG-0002-LFSM",
                                  "matrix": "Eggs"}]
    out = rc.compose_sample_block(rows, True, None)
    markers = [m for _, m in out]
    assert markers == ["sample", "duplicate", "sample"], (
        "the LFSM row must not have been duplicated: {0}".format(markers))


# ── lfsm_frequency ────────────────────────────────────────────────────────────

def test_lfsm_frequency_inserts_every_nth_field_sample():
    rows = _rows(*["S-{0:02d}".format(i) for i in range(1, 11)])  # 10 samples
    out = rc.compose_sample_block(rows, None, 5)
    markers = [m for _, m in out]
    # an "lfsm" marker after the 5th and after the 10th field sample.
    assert markers.count("lfsm") == 2, markers
    lfsm_idx = [i for i, m in enumerate(markers) if m == "lfsm"]
    assert markers[lfsm_idx[0] - 1] == "sample"
    # confirm it lands right after the 5th sample row, not earlier/later.
    sample_positions = [i for i, m in enumerate(markers) if m == "sample"]
    assert lfsm_idx[0] == sample_positions[4] + 1


def test_lfsm_frequency_counts_field_samples_not_duplicate_rows():
    """The bug this test exists to catch: with duplicate_all_samples ALSO on,
    'every 5 samples' must still mean 5 FIELD samples, not 5 injections --
    counting the duplicate rows would fire an LFSM every 2.5 field samples."""
    rows = _rows(*["S-{0:02d}".format(i) for i in range(1, 6)])  # 5 samples
    out = rc.compose_sample_block(rows, True, 5)
    markers = [m for _, m in out]
    # 5 samples * (sample + duplicate) = 10 rows, then exactly ONE lfsm at
    # the end -- not two, which is what counting duplicates would produce.
    assert markers.count("lfsm") == 1, markers
    assert markers[-1] == "lfsm", markers


def test_lfsm_frequency_skips_registered_qc_rows_when_counting():
    """A registered LFSM/MB row in sample_rows does not itself advance the
    field-sample counter (it is not a field sample), matching how it is
    also never duplicated."""
    rows = (_rows("S-01", "S-02", "S-03", "S-04") +
            [{"sample_id": "S-EXTRA-LFSM", "matrix": "Eggs"}] +
            _rows("S-05"))
    out = rc.compose_sample_block(rows, None, 5)
    markers = [m for _, m in out]
    # 5 FIELD samples total (the LFSM row doesn't count) -> exactly one
    # lfsm marker, at the end.
    assert markers.count("lfsm") == 1, markers
    assert markers[-1] == "lfsm", markers


def test_lfsm_frequency_none_or_non_numeric_is_identity():
    rows = _rows("S-01", "S-02")
    for bad in (None, 0, -3, "not-a-number", ""):
        out = rc.compose_sample_block(rows, None, bad)
        assert out == [(r, "sample") for r in rows], (bad, out)


if __name__ == "__main__":
    ok = fail = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                fail += 1
                print("FAIL", name, "--", exc)
            else:
                ok += 1
                print("PASS", name)
    print("{0} passed, {1} failed".format(ok, fail))
    if fail:
        sys.exit(1)
