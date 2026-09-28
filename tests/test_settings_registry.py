# -*- coding: utf-8 -*-
"""The settings registry: one declared home for every lab-owned setting.

WHY THESE TESTS AND NOT OTHERS
------------------------------
The registry exists so a lab admin can make small edits without touching code
(CLAUDE.md §1 rule 1). Three things could make it *worse* than the per-feature
status quo, and each has a real precedent in this codebase:

  1. **A seed that silently wins.** `balance_tolerance` is collected by a form,
     saved by a handler, and never read by the code that decides whether a
     balance passes — `facility_qc.py:865` reads the module constant instead. So
     "editable" and "effective" are different claims, and the registry must not
     let a judging setting fall back to a believable number
     (tests/test_unconfigured_criteria.py records why: ~59 inline fallbacks once
     meant "a profile that said nothing produced a believable limit and no one
     was told").
  2. **Two owners for one fact.** `senaite.pfas.lab_settings` is already taken by
     `browser/reagents.py:53`; WIRING.md §1.4 exists to report duplicate keys
     after the fact. `register()` refuses them up front instead.
  3. **A seed correction that never reaches the lab.** `save_library` stores only
     what differs from the seed for exactly this reason. Storing everything would
     freeze today's defaults into every instance forever.

Annotation access is faked with the same injected-module idiom as
tests/test_worksheet_criteria_snapshot.py:72 — `zope.annotation` is not
importable under the Py3 test interpreter, and the production module must not
grow a test-only seam to accommodate that.
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "src", "senaite", "pfas", "settings_registry.py")


# ── The fake annotation store, per the house idiom ───────────────────────────

def _fake_iannotations(obj):
    """A persistent per-object dict, like the real AttributeAnnotations adapter:
    annotate an object and get the SAME store back next time. Held as an
    attribute ON the object rather than keyed by id(), which would collide once
    a garbage-collected fake's address were reused."""
    if not hasattr(obj, "_fake_annotations"):
        obj._fake_annotations = {}
    return obj._fake_annotations


def _install_annotation_fake():
    if "zope.annotation.interfaces" in sys.modules:
        return
    iface = types.ModuleType("zope.annotation.interfaces")
    iface.IAnnotations = _fake_iannotations
    ann = types.ModuleType("zope.annotation")
    ann.interfaces = iface
    zope = sys.modules.get("zope") or types.ModuleType("zope")
    zope.annotation = ann
    sys.modules["zope"] = zope
    sys.modules["zope.annotation"] = ann
    sys.modules["zope.annotation.interfaces"] = iface


class _FakePortal(object):
    """Stands in for the Plone site object the settings live on."""


def _fresh():
    """A registry module with an empty declaration table.

    Loaded by path per file, so one test's registrations cannot leak into
    another's — `register()` refuses duplicates, which would otherwise turn an
    unrelated test into a spurious failure.
    """
    _install_annotation_fake()
    spec = importlib.util.spec_from_file_location(
        "pfas_settings_registry_under_test", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._clear_registry_for_tests()
    return mod, _FakePortal()


def _lab(mod, **kw):
    """A plain non-judging lab setting with a seed."""
    base = dict(key="t.thing", group=mod.GROUP_THRESHOLDS, label=u"Thing",
                kind=mod.KIND_FLOAT, tier=mod.TIER_LAB, seed=1.5, unit=u"g")
    base.update(kw)
    return mod.register(**base)


# ── Declaration contract ─────────────────────────────────────────────────────

def test_a_duplicate_key_is_refused_at_declaration():
    """Rule 3 enforced where WIRING.md §1.4 can only report."""
    mod, _ = _fresh()
    _lab(mod)
    try:
        _lab(mod)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("a duplicate key was accepted")


def test_a_judging_setting_may_not_carry_a_seed():
    """The combination defeats refuse-to-judge: an unset acceptance criterion
    would resolve to a believable number instead of blocking."""
    mod, _ = _fresh()
    try:
        _lab(mod, key="t.limit", judging=True, seed=70.0)
    except ValueError as exc:
        assert "judging" in str(exc).lower()
    else:
        raise AssertionError("judging + seed was accepted")


def test_a_judging_setting_without_a_seed_is_fine():
    mod, _ = _fresh()
    s = _lab(mod, key="t.limit", judging=True, seed=mod.NO_SEED)
    assert s.judging and not s.has_seed


def test_unknown_group_tier_kind_and_storage_are_refused():
    mod, _ = _fresh()
    for kw, word in ((dict(group="nope"), "group"),
                     (dict(tier="nope"), "tier"),
                     (dict(kind="nope"), "kind"),
                     (dict(storage="nope"), "storage")):
        try:
            _lab(mod, key="t." + word, **kw)
        except ValueError as exc:
            assert word in str(exc)
        else:
            raise AssertionError("bad %s accepted" % word)


def test_a_linked_setting_must_say_how_to_describe_itself():
    """Otherwise the console lists a row it cannot fill in."""
    mod, _ = _fresh()
    try:
        _lab(mod, key="t.linked", storage=mod.STORAGE_LINKED)
    except ValueError as exc:
        assert "describe_hook" in str(exc)
    else:
        raise AssertionError("a linked setting with no hook was accepted")


# ── Reading: the two paths, and why they differ ──────────────────────────────

def test_an_unset_judging_setting_refuses_rather_than_substituting():
    mod, portal = _fresh()
    _lab(mod, key="t.limit", label=u"Recovery minimum", judging=True,
         seed=mod.NO_SEED, owner_view="@@pfas-lab-settings")
    try:
        mod.get(portal, "t.limit")
    except mod.UnconfiguredSetting as exc:
        # The message has to tell a person what to do, not just fail.
        assert "Recovery minimum" in str(exc)
        assert "@@pfas-lab-settings" in str(exc)
    else:
        raise AssertionError("an unset judging setting returned a value")


def test_describe_never_raises_for_the_same_setting():
    """The console must be able to RENDER the unset rows — they are the ones
    that block a run. If describe() raised, the rows that matter most would be
    the ones it could not draw."""
    mod, portal = _fresh()
    _lab(mod, key="t.limit", judging=True, seed=mod.NO_SEED)
    row = mod.describe(portal, "t.limit")
    assert row["source"] == "unset"
    assert row["value"] is None
    assert row["judging"] is True


def test_a_non_judging_setting_falls_back_to_its_seed():
    mod, portal = _fresh()
    _lab(mod)
    assert mod.get(portal, "t.thing") == 1.5
    assert mod.describe(portal, "t.thing")["source"] == "seed"


def test_an_unregistered_key_is_an_error_not_a_guess():
    mod, portal = _fresh()
    try:
        mod.get(portal, "t.nope")
    except KeyError:
        pass
    else:
        raise AssertionError("an unregistered key returned a value")


def test_unconfigured_lists_exactly_the_judging_settings_with_no_value():
    mod, portal = _fresh()
    _lab(mod, key="t.a")                                    # seeded, not judging
    _lab(mod, key="t.b", judging=True, seed=mod.NO_SEED)    # unset, judging
    _lab(mod, key="t.c", judging=True, seed=mod.NO_SEED)
    mod.set_value(portal, "t.c", 70.0)                      # now configured
    keys = [r["key"] for r in mod.unconfigured(portal)]
    assert keys == ["t.b"], keys


# ── Writing: only the difference is stored ───────────────────────────────────

def test_only_the_difference_from_the_seed_is_stored():
    """`save_library`'s trim rule, generalised: a seed correction must still
    reach a lab that never overrode the value."""
    mod, portal = _fresh()
    _lab(mod)
    assert mod.set_value(portal, "t.thing", 2.5) is True
    stored = _fake_iannotations(portal)[mod.ANNOTATION_KEY]
    assert '"t.thing"' in stored
    # Setting it back to the seed REMOVES the override rather than storing it.
    assert mod.set_value(portal, "t.thing", 1.5) is True
    import json
    assert json.loads(_fake_iannotations(portal)[mod.ANNOTATION_KEY])["overrides"] == {}
    assert mod.describe(portal, "t.thing")["source"] == "seed"


def test_nothing_is_written_when_the_value_is_unchanged():
    mod, portal = _fresh()
    _lab(mod)
    mod.set_value(portal, "t.thing", 2.5)
    before = _fake_iannotations(portal)[mod.ANNOTATION_KEY]
    assert mod.set_value(portal, "t.thing", 2.5) is False
    assert _fake_iannotations(portal)[mod.ANNOTATION_KEY] == before


def test_an_override_wins_and_is_flagged_customised():
    mod, portal = _fresh()
    _lab(mod)
    mod.set_value(portal, "t.thing", 9.0)
    row = mod.describe(portal, "t.thing")
    assert row["value"] == 9.0
    assert row["source"] == "override"
    assert row["customised"] is True
    assert row["seed"] == 1.5, "the seed must stay visible beside the override"


def test_the_caller_cannot_write_outside_its_tier():
    """A missing check in one view must not be able to widen the registry."""
    mod, portal = _fresh()
    _lab(mod, key="t.vocab", tier=mod.TIER_STRUCTURAL, kind=mod.KIND_LIST,
         seed=[u"a"])
    try:
        mod.set_value(portal, "t.vocab", [u"a", u"b"],
                      allowed_tiers=(mod.TIER_LAB,))
    except ValueError as exc:
        assert "tier" in str(exc)
    else:
        raise AssertionError("a lab-tier caller wrote a structural setting")
    # With the right authority it goes through.
    assert mod.set_value(portal, "t.vocab", [u"a", u"b"],
                         allowed_tiers=(mod.TIER_STRUCTURAL,)) is True


def test_the_console_may_not_write_a_setting_another_editor_owns():
    """The single most important boundary: a second writer to data another
    editor owns would recreate the split-key defect at a larger scale."""
    mod, portal = _fresh()
    _lab(mod, key="t.linked", storage=mod.STORAGE_LINKED,
         owner_view="@@pfas-print-settings",
         describe_hook=lambda p, s: {"value": 3.0, "seed": 3.0,
                                     "source": "seed"})
    try:
        mod.set_value(portal, "t.linked", 4.0)
    except ValueError as exc:
        assert "@@pfas-print-settings" in str(exc)
    else:
        raise AssertionError("the registry wrote a linked setting")


# ── Linked and derived settings ──────────────────────────────────────────────

def test_a_linked_setting_reports_its_owner_value():
    mod, portal = _fresh()
    _lab(mod, key="t.linked", storage=mod.STORAGE_LINKED,
         owner_view="@@pfas-facility-units",
         describe_hook=lambda p, s: {"value": 0.002, "seed": 0.001,
                                     "source": "override",
                                     "customised": True})
    row = mod.describe(portal, "t.linked")
    assert row["value"] == 0.002 and row["customised"] is True
    assert mod.get(portal, "t.linked") == 0.002


def test_a_broken_hook_shows_as_unknown_rather_than_blanking_the_console():
    mod, portal = _fresh()

    def _boom(p, s):
        raise RuntimeError("the owning store is down")

    _lab(mod, key="t.linked", storage=mod.STORAGE_LINKED,
         describe_hook=_boom)
    row = mod.describe(portal, "t.linked")
    assert row["source"] == "unknown", row


def test_a_derived_setting_is_listed_but_never_editable():
    """So an admin stops hunting for an editor that must not exist."""
    mod, portal = _fresh()
    _lab(mod, key="t.derived", storage=mod.STORAGE_DERIVED,
         describe_hook=lambda p, s: {"value": [u"x"], "source": "derived"})
    row = mod.describe(portal, "t.derived")
    assert row["source"] == "derived" and row["customised"] is False
    try:
        mod.set_value(portal, "t.derived", [u"y"])
    except ValueError:
        pass
    else:
        raise AssertionError("a derived setting was written")


# ── Coercion, validation, robustness ────────────────────────────────────────

def test_a_value_is_coerced_to_its_declared_kind():
    mod, portal = _fresh()
    _lab(mod, key="t.f", kind=mod.KIND_FLOAT, seed=1.0)
    _lab(mod, key="t.i", kind=mod.KIND_INT, seed=1)
    _lab(mod, key="t.b", kind=mod.KIND_BOOL, seed=False)
    mod.set_value(portal, "t.f", "2.5")
    mod.set_value(portal, "t.i", "7")
    mod.set_value(portal, "t.b", "on")
    assert mod.get(portal, "t.f") == 2.5
    assert mod.get(portal, "t.i") == 7
    assert mod.get(portal, "t.b") is True


def test_a_non_numeric_value_is_refused_with_a_readable_message():
    mod, portal = _fresh()
    _lab(mod, label=u"Balance tolerance")
    try:
        mod.set_value(portal, "t.thing", "widget")
    except ValueError as exc:
        assert "Balance tolerance" in str(exc), str(exc)
    else:
        raise AssertionError("a non-numeric value was stored in a float setting")


def test_a_choice_outside_its_vocabulary_is_refused():
    mod, portal = _fresh()
    _lab(mod, key="t.c", kind=mod.KIND_CHOICE, choices=[u"a", u"b"], seed=u"a")
    try:
        mod.set_value(portal, "t.c", u"z")
    except ValueError as exc:
        assert "not one of" in str(exc)
    else:
        raise AssertionError("an out-of-vocabulary choice was stored")


def test_unparseable_stored_data_falls_back_to_seeds_instead_of_breaking():
    """Same posture as facility_qc: a corrupt blob must not break every page
    that reads a setting."""
    mod, portal = _fresh()
    _lab(mod)
    _fake_iannotations(portal)[mod.ANNOTATION_KEY] = "{not json"
    assert mod.get(portal, "t.thing") == 1.5
    assert mod.describe(portal, "t.thing")["source"] == "seed"


def test_no_portal_yields_seeds_so_headless_callers_keep_working():
    """`get_facility_defaults(portal=None)` documents this degradation; the
    worker and migration scripts have no portal."""
    mod, _ = _fresh()
    _lab(mod)
    assert mod.get(None, "t.thing") == 1.5


def test_describe_all_reads_the_annotation_once():
    """A console doing N annotation reads for N rows would get slower with every
    setting registered."""
    mod, portal = _fresh()
    for i in range(6):
        _lab(mod, key="t.k%d" % i)
    calls = []
    real = mod._load

    def _counting(portal_arg):
        calls.append(1)
        return real(portal_arg)

    mod._load = _counting
    rows = mod.describe_all(portal)
    mod._load = real
    assert len(rows) == 6
    assert len(calls) == 1, "describe_all read the annotation %d times" % len(calls)


def test_the_audit_trail_is_capped():
    """The audit list shares the annotation with the overrides, so an uncapped
    list would make every write rewrite a growing blob."""
    mod, portal = _fresh()
    _lab(mod, kind=mod.KIND_INT, seed=0)
    mod.AUDIT_LIMIT = 5
    for i in range(1, 12):
        mod.set_value(portal, "t.thing", i, actor=u"tester")
    import json
    data = json.loads(_fake_iannotations(portal)[mod.ANNOTATION_KEY])
    assert len(data["audit"]) <= 5, len(data["audit"])
    assert mod.last_changed(portal, "t.thing")["actor"] == u"tester"


# ── Ordering and grouping ───────────────────────────────────────────────────

def test_settings_are_grouped_in_the_order_the_lab_asked_for():
    mod, _ = _fresh()
    _lab(mod, key="t.w", group=mod.GROUP_WORDING)
    _lab(mod, key="t.q", group=mod.GROUP_QC_LIMITS)
    _lab(mod, key="t.t", group=mod.GROUP_THRESHOLDS)
    _lab(mod, key="t.v", group=mod.GROUP_VOCABULARY)
    assert [s.group for s in mod.registered()] == list(mod.GROUPS)
    assert set(mod.GROUP_LABELS) == set(mod.GROUPS), \
        "every group needs a human label for the console"


def test_the_annotation_key_does_not_collide_with_an_existing_one():
    """`senaite.pfas.lab_settings` belongs to browser/reagents.py:53. Reusing it
    would create the duplicate WIRING.md §1.4 reports."""
    mod, _ = _fresh()
    assert mod.ANNOTATION_KEY == u"senaite.pfas.settings_registry"
    reagents = os.path.join(ROOT, "src", "senaite", "pfas", "browser",
                            "reagents.py")
    with open(reagents) as fh:
        assert mod.ANNOTATION_KEY not in fh.read()


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
