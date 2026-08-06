"""Control material must be recognised as control material.

`classify_injection` defaults to `"Sample"`, and until 2026-08-05 that default
swallowed every blank whose name did not happen to contain `MB` as a
whitespace-delimited token. Verified before the fix: `MxB-260805`, `LRB-01`,
`LFB-01` and even `MB-01` all classified as `Sample`, and `Dup-01` classified as
`LFSMD` — a different QC type with different acceptance criteria.

The consequences were not "a blank is sent to a client" — the push requires a
matching SENAITE sample, so an odd blank is not filed. They were worse in a
quieter way:

  * the blank's contamination was never judged, because the check keys on the role
  * it was not used for `< LOD` blank subtraction
  * it appeared as a reportable row in the batch PDF
  * under qualified release it would count as CLIENT material, so its failures
    would be excused as a matrix effect instead of holding the batch

**The default cannot be made strict.** A client sample has no positive marker —
`KCP Silage "Egg-1" Sample`, `FDA_32PFAS-FEED-0002` and `2518592` all reach the
fallback. Making the fallback non-reportable would stop reporting every genuine
sample. The safety comes from recognising control material exhaustively, and
from `classification_rule()` letting a caller tell a positive identification
from a default.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline.importer import classify_injection, classification_rule

CONTROL_CASES = [
    ("MxB-260805", "MxB"),
    ("Matrix Blank 1", "MxB"),
    ("LRB-01", "LRB"),
    ("Lab Reagent Blank 1", "LRB"),
    ("LFB-01", "LFB"),
    ("Lab Fortified Blank", "LFB"),
    ("LCS-01", "LFB"),               # LCS folds into LFB, documented
    ("CCB-01", "CCB"),
    ("FDA_32PFAS-CCB-260803-01", "CCB"),
    ("MB-01", "MB"),
    ("KCP Water MB 2025-10-20-01", "MB"),
    ("Method Blank 3", "MB"),
    ("FDA-CCV-251020", "CCV"),
    ("FDA-ICV-251020", "ICV"),
    ("FDA-CAL-1-251006", "CAL"),
    ("Dup-01", "Dup"),
    ("KCP Silage Dup 2025-10-20-1", "Dup"),
    ('KCP Silage "Egg-2" LFSM Mid', "LFSM"),
    ('KCP Silage "Egg-2" LFSM Mid Duplicate', "LFSMD"),
    ("LFSMD-01", "LFSMD"),
]

SAMPLE_CASES = [
    'KCP Silage "Egg-1" Sample',
    "FDA_32PFAS-FEED-0002",
    "2518592",
    "Egg-1",
]


def test_control_material_is_recognised():
    wrong = [(n, classify_injection(n, {}), want)
             for n, want in CONTROL_CASES
             if classify_injection(n, {}) != want]
    assert not wrong, wrong


def test_lfsmd_wins_over_lfsm_and_dup():
    """Order matters twice: LFSMD contains LFSM, and 'Duplicate' can sit any
    distance after the LFSM token ('LFSM Mid Duplicate' is the real form)."""
    assert classify_injection('X LFSM Mid Duplicate', {}) == "LFSMD"
    assert classify_injection('X LFSM Mid', {}) == "LFSM"
    # a plain sample duplicate is NOT a matrix-spike duplicate
    assert classify_injection("Dup-01", {}) == "Dup"


def test_real_samples_still_classify_as_samples():
    """The fallback is load-bearing — do not make it strict."""
    for name in SAMPLE_CASES:
        assert classify_injection(name, {}) == "Sample", name
        assert classification_rule(name, {}) == "", (
            "%s should reach the fallback, not a positive rule" % name)


def test_positive_identification_is_distinguishable_from_the_default():
    assert classification_rule("MB-01", {}) == "MB"
    assert classification_rule("2518592", {}) == ""


def test_dilution_beats_every_name_rule():
    """A dilution's role comes from FM-ENV-252, never from the name."""
    name = 'KCP Silage "Egg-3"; Dil. 1:10'
    assert classify_injection(name, {}) == "Sample"
    assert classify_injection(name, {name: {"parent": "x", "factor": 10}}) == "Dilution"


def test_every_classified_role_has_review_checks():
    """A role with no entry silently inherits REVIEW_CHECKS['Sample'] — which is
    how a blank would be given a client sample's checks."""
    from pfas_pipeline.injection_builder import REVIEW_CHECKS
    roles = {want for _n, want in CONTROL_CASES} | {"Sample"}
    missing = sorted(r for r in roles if r not in REVIEW_CHECKS)
    assert not missing, "roles with no review checks: %s" % missing


def test_blank_roles_are_not_client_reportable():
    """REPORTED_ROLES decides what reaches the summary and the batch PDF."""
    import inspect
    from pfas_pipeline import pipeline
    src = inspect.getsource(pipeline.build_summary)
    assert 'REPORTED_ROLES = ("Sample", "MB", "LFSM", "LFSMD")' in src, (
        "REPORTED_ROLES changed — re-check that blanks stay out of it")
    for role in ("MxB", "LRB", "CCB", "Dup"):
        assert '"%s"' % role not in 'REPORTED_ROLES = ("Sample", "MB", "LFSM", "LFSMD")'


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
