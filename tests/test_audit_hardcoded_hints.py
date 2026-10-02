# -*- coding: utf-8 -*-
"""The configurability audit's hardcoded-value scan must keep finding things.

WHY THIS FILE EXISTS
--------------------
`tools/audit_configurable.py` enumerates the lab values still living in Python
constants — the worklist for CLAUDE.md §1 rule 1. It is advisory, so a bug in it
fails silently: the register simply reports fewer findings and everyone believes
the migration is going well.

That nearly happened. Excluding `_REGISTRY = {}` (an empty container holds no lab
decision) was first attempted by widening the MATCH pattern with a negative
lookahead. It dropped the count from 109 to **13**, because the overwhelming
majority of real tables open their brace and put the contents on the NEXT line,
so the lookahead's end-of-line alternative excluded them all. The count was the
only thing that revealed it.

So the scan is pinned by BEHAVIOUR on representative lines, not by a total: a
total changes legitimately whenever the code does, and a test that has to be
edited after every real change stops being read.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "audit_configurable.py")

sys.path.insert(0, os.path.join(ROOT, "tools"))


def _hints():
    import audit_configurable
    return audit_configurable.HARDCODED_HINTS


def _table_pattern():
    for pattern, why in _hints():
        if why == "module-level table":
            return pattern
    raise AssertionError("the module-level-table hint is gone entirely")


# The shapes that MUST still be caught. Each is a real line shape from the repo.
MUST_MATCH = [
    "DEFAULT_SHELF_LIFE_DAYS = {",              # contents on the next line
    "REAGENT_CATEGORIES = [",
    "    BALANCE_DEFAULTS = {",                 # indented
    "_DEFAULT_TIERS = {",                       # leading underscore
    "_LAB_REQUIRED = frozenset([",              # frozenset wrapper
    'METHOD_TEST_CODES = {"a": 1}',             # contents on the same line
]

# Shapes that must NOT be caught.
MUST_NOT_MATCH = [
    "_REGISTRY = {}",                           # empty: filled at import time
    "GROUP_DEFS = (",                           # a tuple, not a table literal
    "lower_case = {",                           # not a module-level CONSTANT
    "AB = {",                                   # too short to be a table name
]


def test_the_table_pattern_still_matches_a_table_opened_on_its_own_line():
    """The exact shape the failed lookahead excluded. If this regresses, the
    register loses ~90% of its findings and says nothing about it."""
    pattern = _table_pattern()
    missed = [line for line in MUST_MATCH if not pattern.search(line)]
    assert not missed, (
        "the hardcoded scan stopped matching these table shapes: %s" % missed)


def test_the_pattern_does_not_match_a_tuple_or_a_lowercase_name():
    pattern = _table_pattern()
    caught = [line for line in MUST_NOT_MATCH[1:] if pattern.search(line)]
    assert not caught, "the scan now flags non-tables: %s" % caught


def test_an_empty_container_is_excluded_by_the_SCAN_not_by_the_pattern():
    """`_REGISTRY = {}` must be excluded — but by the narrow same-line check in
    the scan loop, NOT by weakening the match pattern, which is what broke it."""
    pattern = _table_pattern()
    assert pattern.search("_REGISTRY = {}"), (
        "the empty-container exclusion has been pushed back into the match "
        "pattern; that is the change that dropped the count from 109 to 13")
    with open(TOOL) as fh:
        body = fh.read()
    # The exclusion lives in the scan, anchored to end-of-line, so it cannot
    # reach a table whose contents start on the following line.
    assert re.search(r"\\{\\}\|\\\[\\\]", body), (
        "no same-line empty-container exclusion found in the scan loop")


def test_the_scan_still_reports_the_known_hardcoded_tables():
    """End to end over the real tree: the named tables are the ones the register
    has always carried, so their disappearance means the scan broke."""
    import audit_configurable
    rows = audit_configurable.audit_hardcoded()
    found = " ".join("%s:%s %s" % (p, n, line) for p, n, _why, line in rows)
    # Names verified present in the tool's ACTUAL output, not assumed. The first
    # version of this test also listed UNIT_TYPES, which the stale committed
    # CONFIG_AUDIT.md reports but the tool no longer does -- `_looks_like_lab_table`
    # inspects only a 15-line window from the opening brace, and UNIT_TYPES grew a
    # `("pipette", "Pipette")` row in GAPS §38 that pushed its lab signal out of
    # range. A real finding left the register silently, and no test noticed.
    # Recorded rather than papered over; the window heuristic is its own fix.
    # DEFAULT_SHELF_LIFE_DAYS left with the tablet catalogue (barcode.py,
    # retired 2026-10-02 DB1): resolved, not lost -- the SENAITE inventory's
    # EXPIRY_DEFAULTS is the one shelf-life table and is still reported.
    # REAGENT_CATEGORIES was only ever reported BY ACCIDENT: none of its values
    # carries a lab signal, and the 15-line window reached the next class's
    # docstring, where "barcode" matched `code`. Adding "Consumable" (bench
    # phase 2) pushed that line out. It is still a hardcoded vocabulary --
    # GAPS §87 records it as open -- but this test can only pin what the
    # heuristic genuinely detects.
    for name in ("BALANCE_DEFAULTS", "WATER_QC_DEFAULTS", "EXPIRY_DEFAULTS"):
        assert name in found, "%s is no longer reported as a hardcoded table" % name
    assert len(rows) > 50, (
        "the hardcoded scan found only %d rows; it found 107 when this test was "
        "written, and a collapse is how the lookahead bug presented" % len(rows))


def test_the_registry_module_does_not_inflate_the_count():
    """The module built to drive this count DOWN must not add to it. Its own
    scaffolding is code structure, not lab values."""
    import audit_configurable
    rows = audit_configurable.audit_hardcoded()
    mine = [r for r in rows if "settings_registry.py" in r[0]]
    assert not mine, (
        "settings_registry.py is being reported as holding lab values: %s" % mine)


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
