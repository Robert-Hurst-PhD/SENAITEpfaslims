# -*- coding: utf-8 -*-
"""A lot is judged expired against the day it was USED, not against today.

DECISIONS.md 2026-08-03 item 7 decided this; `reagents._is_expired` grew an `as_of`
parameter and nothing ever passed it. Judging against today makes a released batch
LESS defensible as time passes: every standard on this instance is expired now, yet
the runs that used them were in date at the time, so a gate keyed on today would
retroactively condemn correct work — the opposite of its purpose.

Two things this file exists to pin, both found by writing it:

  * **there is no single use date.** On the real released WS-0005 the FM-ENV-253
    processing date is 2025-10-17 and the FM-ENV-252 extraction date is 2026-08-03 —
    ten months apart. Each logbook carries the date ITS OWN rows were used.
  * **the first version of the reagent check could never fire.** It was handed
    `_reagent_dict`, the DISPLAY projection (title, url, supplier, cat_number,
    lot_number, has_coa), which carries no expiry at all, so `_effective_expiry`
    returned "" and every reagent read as in date. Caught by asking the check to
    fail on a use date of 2030 and watching it pass.

AST rather than import: `data_review.py` is Zope-bound. Same technique as
tests/test_attestation_kind.py.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_REVIEW = os.path.join(ROOT, "src", "senaite", "pfas", "browser",
                           "data_review.py")
REAGENTS = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "reagents.py")


def _source():
    with open(DATA_REVIEW) as fh:
        return fh.read()


def _func(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in data_review.py" % name)


def _seg(src, name):
    node = _func(src, name)
    lines = src.splitlines()
    return "\n".join(lines[node.lineno - 1:node.body[-1].lineno + 4])


# ── The decision ─────────────────────────────────────────────────────────────

def test_the_gate_judges_expiry_as_of_the_use_date_at_all():
    src = _source()
    assert "_expired_at_use" in src, (
        "nothing judges a lot against the date it was used; _is_expired's `as_of` "
        "is still unused (DECISIONS.md 2026-08-03 item 7)")
    seg = _seg(src, "_expired_at_use")
    assert "date.today" not in seg, (
        "judging against today retroactively condemns work that was correct when "
        "it was performed")
    assert "as_of=" in seg, "the use date must reach reagents._is_expired"


def test_each_logbook_supplies_its_own_use_date():
    """A worksheet-wide date would condemn one set of lots or excuse the other."""
    src = _source()
    tree_fn = _seg(src, "_build_traceability_tree")
    assert 'self._use_date(lb252, "extraction_date")' in tree_fn, \
        "FM-ENV-252 rows must be judged against the extraction date"
    assert 'self._use_date(lb251, "prepared_date")' in tree_fn, \
        "FM-ENV-251 rows must be judged against that logbook's prepared date"


def test_an_unknown_use_date_warns_and_does_not_block():
    """An unrecorded date is not evidence of expiry. Same posture the equipment
    walk takes for an unregistered serial: only an ESTABLISHED unmet obligation
    blocks release."""
    src = _source()
    seg = _seg(src, "_expired_at_use")
    assert "if not resolved or not use_date:" in seg and "return None" in seg, (
        "a missing use date must not be treated as expiry")
    tree_fn = _seg(src, "_build_traceability_tree")
    assert 'tree["warnings"].append(' in tree_fn, (
        "a logbook with no date must be REPORTED — silently skipping the check is "
        "how an unenforced obligation looks identical to a satisfied one")


# ── The defect: a check that could not fire ──────────────────────────────────

def test_the_expiry_decision_never_gets_the_display_projection():
    """`_reagent_dict` has no expiry field, so handing it to the expiry resolver
    produces a check that always answers 'in date'."""
    src = _source()
    # AST, not lines. The first version scanned line by line and the call spans
    # two — `self._expired_at_use(` on one, its first argument on the next — so
    # reintroducing the real defect left the test passing. The mutation check is
    # what caught that, for the second time in this codebase (GAPS §41.6).
    fn = _func(src, "_build_traceability_tree")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_expired_at_use"]
    assert calls, "the gate makes no expiry-at-use decision at all"
    for call in calls:
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute):
            assert first.func.attr != "_reagent_dict", (
                "line %d: the expiry decision is made on the display projection, "
                "which carries no expiry, so the check can never fire"
                % call.lineno)
    assert "_reagent_record" in src, (
        "the full reagent record accessor is missing")


def test_reagent_dict_really_has_no_expiry_so_the_rule_above_matters():
    """Pins the premise rather than trusting it: if `_reagent_dict` ever grows an
    expiry field, the rule above becomes unnecessary and should be revisited
    deliberately, not silently."""
    src = _source()
    seg = _seg(src, "_reagent_dict")
    assert "expiry" not in seg, (
        "_reagent_dict now carries an expiry — re-examine "
        "test_the_expiry_decision_never_gets_the_display_projection")


def test_a_prepared_standard_is_judged_on_its_parent_tightened_expiry():
    """A prep whose source CRM expired first expired with it, so the stored date on
    the lot is not the one that counts."""
    seg = _seg(_source(), "_expired_at_use")
    assert "effective_expiry_info" in seg, (
        "a prepared standard must be judged on its inherited expiry")


def test_is_expired_still_takes_as_of_and_documents_why():
    with open(REAGENTS) as fh:
        body = fh.read()
    assert "def _is_expired(rec, as_of=None):" in body
    assert "_expiry_unknown" in body, (
        "an unknown expiry must stay distinguishable from a known-good one")


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
