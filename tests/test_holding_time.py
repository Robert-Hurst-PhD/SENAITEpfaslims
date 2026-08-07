"""Holding time must be computed, and must refuse rather than guess.

CLAUDE.md §10: "Holding times are a hard acceptance criterion. EPA 537.1: 14
days for drinking water PFAS." Until 2026-08-06 nothing in this system computed
one. `holding_time_ok` was a checkbox, no method profile carried a limit, and
the only evidence a sample had been extracted in time was that somebody ticked
a box.

The two dates were BOTH already being recorded and never read together:
`sample_collection_date` on the Chain of Custody and `extraction_date` on
FM-ENV-252. That is this project's recurring defect shape — a fact recorded
correctly in one place and never carried to where it is used.

What these tests pin, in order of what would hurt most if it broke:

  * an unset limit REFUSES, it does not pass. Seeding a plausible number for
    FDA or 1633A would have been fabricating a regulatory value (§8), and
    treating the resulting blank as "fine" is how a silent default becomes a
    released result.
  * an ambiguous date is not guessed. `03/04/2025` is 3 April or 4 March
    depending on who typed it, and this decides whether a result is defensible.
  * only EPA 537.1 is seeded, at 14 days, because §10 documents it.

`holding_time` imports nothing from Plone so it can be tested outside the
container, and must stay that way; `test_the_module_stays_plone_free` enforces
it.
"""
import ast
import datetime
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "src", "senaite", "pfas", "holding_time.py")

# Loaded by path, NOT as senaite.pfas.holding_time: importing the package would
# pull in zope.i18nmessageid via its __init__, which is the dependency this
# module is deliberately free of.
def _load(path, name):
    """Py2 `imp` is gone in 3.12; this works on both."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except ImportError:
        import imp
        return imp.load_source(name, path)


ht = _load(MODULE, "pfas_holding_time_under_test")


def test_an_unset_limit_refuses_to_judge():
    """The most important case. 17 of 18 method x matrix combinations have no
    holding time configured, and every one of them must say so rather than
    report a pass."""
    for limit in (None, "", 0, -1, "abc"):
        profile = {"holding_times": {"Eggs": limit}}
        got = ht.limit_for(profile, "Eggs")
        assert got is None, (limit, got)
    verdict = ht.evaluate("2025-10-15", "2025-10-16", None)
    assert verdict["status"] == ht.UNCONFIGURED, verdict
    assert verdict["status"] != ht.OK
    assert "Matrices & Units" in verdict["message"], verdict["message"]


def test_a_missing_date_refuses_and_names_which_one():
    """A reviewer who is told only 'cannot calculate' will tick past it."""
    v = ht.evaluate(None, "2025-10-20", 14)
    assert v["status"] == ht.NO_DATES
    assert "Chain of Custody" in v["message"], v["message"]

    v = ht.evaluate("2025-10-15", None, 14)
    assert v["status"] == ht.NO_DATES
    assert "FM-ENV-252" in v["message"], v["message"]


def test_within_and_beyond_the_limit():
    assert ht.evaluate("2025-10-15", "2025-10-15", 14)["status"] == ht.OK
    assert ht.evaluate("2025-10-15", "2025-10-29", 14)["status"] == ht.OK, "14 == the limit"
    v = ht.evaluate("2025-10-15", "2025-10-30", 14)
    assert v["status"] == ht.EXCEEDED, v
    assert v["elapsed_days"] == 15, v
    assert "15" in v["message"] and "14" in v["message"], v["message"]


def test_the_limit_prints_as_a_whole_number():
    """`within the 14.0 day limit` on a review screen reads as a bug."""
    v = ht.evaluate("2025-10-15", "2025-10-20", 14.0)
    assert "14 day" in v["message"], v["message"]


def test_extraction_before_collection_is_a_defect_not_a_pass():
    """Negative elapsed time would otherwise sail through `elapsed > limit`."""
    v = ht.evaluate("2025-10-20", "2025-10-15", 14)
    assert v["status"] == ht.INVALID, v
    assert v["status"] in ht.BLOCKING


def test_blocking_covers_exactly_the_verdicts_that_must_not_release():
    assert ht.EXCEEDED in ht.BLOCKING
    assert ht.INVALID in ht.BLOCKING
    # refusals are NOT blocking -- they are unanswered, and the gate reports
    # them separately. Making them blocking would stop every batch on every
    # method that has no configured limit, i.e. 17 of 18 combinations.
    assert ht.UNCONFIGURED not in ht.BLOCKING
    assert ht.NO_DATES not in ht.BLOCKING
    assert ht.OK not in ht.BLOCKING


def test_ambiguous_dates_are_refused_not_guessed():
    """`03/04/2025` is 3 April or 4 March. A module that refuses an unset limit
    must not then guess a date that decides whether a result is defensible."""
    for bad in ("03/04/2025", "3/4/25", "04-03-2025", "Oct 15 2025", "", "  "):
        assert ht.parse_date(bad) is None, bad


def test_the_iso_forms_the_widgets_actually_write_are_accepted():
    want = datetime.date(2025, 10, 15)
    for good in ("2025-10-15", "2025-10-15T00:00:00", "2025-10-15 09:30:00",
                 "2025-10-15T09:30", "2025-10-15T09:30:00.123456+00:00"):
        assert ht.parse_date(good) == want, good
    assert ht.parse_date(datetime.date(2025, 10, 15)) == want
    assert ht.parse_date(datetime.datetime(2025, 10, 15, 9, 30)) == want


def test_the_matrix_lookup_tolerates_case_and_whitespace():
    """The profile is keyed by matrix title; the value arrives from a core
    SampleType Title. A trailing space must not silently unconfigure a limit."""
    profile = {"holding_times": {"Drinking Water": 14}}
    for probe in ("Drinking Water", "drinking water", "  Drinking Water  "):
        assert ht.limit_for(profile, probe) == 14, probe
    assert ht.limit_for(profile, "Soil") is None
    assert ht.limit_for({}, "Drinking Water") is None
    assert ht.limit_for({"holding_times": []}, "Drinking Water") is None


def test_only_epa_537_is_seeded_and_it_is_seeded_at_14_days():
    """§8 forbids fabricating a regulatory value. §10 documents 537.1 = 14 days
    and nothing else, so every other method must ship unset."""
    store = os.path.join(ROOT, "src", "senaite", "pfas", "method_profile_store.py")
    with open(store) as fh:
        tree = ast.parse(fh.read(), store)
    seeds = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            # ast.Str.s is gone in 3.14; ast.Constant.value works on both
            name = getattr(key, "value", getattr(key, "s", None))
            if name != "holding_times":
                continue
            src = ast.dump(value)
            seeds["EPA_537_1" if "_EPA537_MATRICES" in src else
                  ("EPA_1633A" if "_EPA1633A_MATRICES" in src else "FDA_32PFAS")] = src
    assert set(seeds) == {"FDA_32PFAS", "EPA_537_1", "EPA_1633A"}, sorted(seeds)
    assert "14" in seeds["EPA_537_1"], seeds["EPA_537_1"]
    for method in ("FDA_32PFAS", "EPA_1633A"):
        assert "None" in seeds[method], (
            "%s ships a holding time; CLAUDE.md documents none for it and §8 "
            "forbids inventing one" % method)


def test_the_module_stays_plone_free():
    """The arithmetic must remain testable without a container."""
    with open(MODULE) as fh:
        tree = ast.parse(fh.read(), MODULE)
    banned = ("zope", "plone", "Products", "bika", "senaite", "AccessControl")
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            assert not name.split(".")[0] in banned, (
                "holding_time imports %s -- it must stay independently "
                "testable" % name)


def test_the_gate_consumes_it():
    """A computation nothing reads is the defect being fixed, not a fix."""
    review = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "data_review.py")
    with open(review) as fh:
        body = fh.read()
    assert "holding_time_summary" in body
    assert "holding_time.BLOCKING" in body, (
        "the CoC gate no longer blocks on a measured breach")
    assert 'senaite.pfas.logbook.252' in body, (
        "the extraction date is no longer read")
    tpl = os.path.join(ROOT, "src", "senaite", "pfas", "browser",
                       "templates", "data_review.pt")
    with open(tpl) as fh:
        assert "holding_time_summary" in fh.read(), (
            "the calculated verdict is not shown on the CoC tab")
    profiles = os.path.join(ROOT, "src", "senaite", "pfas", "browser",
                            "method_profiles.py")
    with open(profiles) as fh:
        prof_body = fh.read()
    assert "mtx_holding" in prof_body and 'profile["holding_times"]' in prof_body, (
        "the limit cannot be set from the UI (Golden Rule 1)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
