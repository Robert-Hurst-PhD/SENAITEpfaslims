# -*- coding: utf-8 -*-
"""One declared home for every lab-owned setting.

WHY THIS EXISTS
---------------
The first rule: *"Configurable, not hardcoded. UI-driven, not code-driven…
Finding a hardcoded lab value = a defect to migrate."* The project has honoured
that repeatedly but PER FEATURE, so three things went wrong at once:

  * a lab admin hunting for "where do I change X" must already know which of six
    sidebar groups owns it;
  * `tools/audit_configurable.py` enforces reachability for the method-profile
    JSON and nothing else, so DEAD settings in other stores are invisible --
    `profiles/default/registry.xml` ships four `senaite.pfas.*` records that
    NOTHING reads, and `balance_tolerance` is collected by a form, saved by a
    handler, and never read by the code that decides whether a balance passes;
  * every surface re-decided what "unset" means.

This module is the single declaration point. A setting registers itself in the
module that owns it, so the console and the audit tool both enumerate the SAME
list and neither carries a hand-maintained copy.

THE PATTERN THIS GENERALISES
----------------------------
`qc_qualification.get_library` / `save_library` (and `facility_qc`'s facility
defaults, independently): seed in code, the lab's edits in a portal annotation,
**saved edits win field by field** so a seed correction still reaches anything the
lab never overrode, and **only the difference is stored**. Both precedents are
kept; this states the semantics once.

TWO READ PATHS, AND WHY
-----------------------
`get()` raises for a JUDGING setting with no value -- the 2026-08-03 "refuse to
judge" decision (tests/test_unconfigured_criteria.py), which exists because ~59
inline fallbacks once meant "a profile that said nothing produced a believable
limit and no one was told". `describe()` NEVER raises, because a console that
lists settings must be able to render the unset ones; if it called `get()` it
could not draw the very rows that matter most.

STORAGE
-------
`IAnnotations(portal)["senaite.pfas.settings_registry"]` -- ONE key, so WIRING.md
gains one entry and credits consumers through these accessors. Not a new storage
tier:'s first rule is already "one ZODB object -> annotate it", and
the portal is one ZODB object.

`senaite.pfas.lab_settings` is NOT used -- `browser/reagents.py:53` owns it for
expiry defaults. Reusing it would create the duplicate-key violation WIRING.md
§1.4 reports.

No `browser.*` imports: stores and views must both be able to import this without
a cycle, the same reasoning `browser/perms.py` records for itself.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

# Production is Py2.7; the test suite is Py3 and loads this module by path, so the
# text type is aliased rather than named directly. Same idiom as
# browser/formutil.py:21.
try:
    _text = unicode                        # noqa: F821  (Py2.7)
except NameError:                          # pragma: no cover  (Py3)
    _text = str

logger = logging.getLogger("senaite.pfas.settings_registry")

ANNOTATION_KEY = u"senaite.pfas.settings_registry"

# Who may change a setting. Manager/LabManager/Owner own lab VALUES; the
# structural tier is narrower because withdrawing a vocabulary term or changing a
# form's field schema can orphan records that already reference it, and a
# published certificate must keep rendering the words it was signed with.
TIER_LAB = u"lab"
TIER_STRUCTURAL = u"structural"
TIERS = (TIER_LAB, TIER_STRUCTURAL)

# The lab owner's four categories, in the order they asked for them.
GROUP_QC_LIMITS = u"qc_limits"
GROUP_VOCABULARY = u"vocabulary"
GROUP_WORDING = u"wording"
GROUP_THRESHOLDS = u"thresholds"
# id and human label declared TOGETHER, so the console's headings cannot drift
# from the ids the settings are registered against. The order is the order the
# groups are shown in.
GROUP_DEFS = (
    (GROUP_QC_LIMITS,  u"QC limits & acceptance criteria"),
    (GROUP_VOCABULARY, u"Vocabularies & dropdown lists"),
    (GROUP_WORDING,    u"Wording on documents"),
    (GROUP_THRESHOLDS, u"Thresholds & schedules"),
)
GROUPS = tuple(g for g, _label in GROUP_DEFS)
GROUP_LABELS = dict(GROUP_DEFS)

KIND_FLOAT = u"float"
KIND_INT = u"int"
KIND_BOOL = u"bool"
KIND_TEXT = u"text"
KIND_CHOICE = u"choice"
KIND_LIST = u"list"
KINDS = (KIND_FLOAT, KIND_INT, KIND_BOOL, KIND_TEXT, KIND_CHOICE, KIND_LIST)

# Where the VALUE lives.
#   registry  -- this module owns it; the console edits it inline
#   linked    -- an existing editor owns it; the console lists and links, never
#                writes. A second writer to data another editor owns would
#                recreate the split-key defect at a larger scale.
#   derived   -- computed from something else; listed so an admin stops hunting
#                for an editor that must not exist
STORAGE_REGISTRY = u"registry"
STORAGE_LINKED = u"linked"
STORAGE_DERIVED = u"derived"
STORAGE = (STORAGE_REGISTRY, STORAGE_LINKED, STORAGE_DERIVED)

# Distinguishes "the lab has not set this" from "the lab set it to nothing".
NO_SEED = object()

# The audit list lives in the same annotation as the overrides, so it cannot be
# allowed to grow without bound -- every write would rewrite a growing blob.
AUDIT_LIMIT = 500


class UnconfiguredSetting(Exception):
    """A judging setting was read and the lab has never set it.

    Deliberately an exception and not a default. See the module docstring: a
    believable substituted limit is worse than a refusal, because a passing
    result never draws a second look.
    """

    def __init__(self, key, label=u"", owner_view=u""):
        self.key = key
        self.label = label
        self.owner_view = owner_view
        where = u" Set it under {0}.".format(owner_view) if owner_view else u""
        msg = (u"{0} ({1}) is not configured, so it cannot be used to judge "
               u"anything.{2}").format(label or key, key, where)
        super(UnconfiguredSetting, self).__init__(msg)


class Setting(object):
    """One declared setting. See `register()` for the contract."""

    def __init__(self, key, group, label, kind, tier,
                 seed=NO_SEED, unit=u"", judging=False,
                 storage=STORAGE_REGISTRY, owner_view=u"", anchor=u"",
                 reader=u"", writer=u"", choices=None,
                 describe_hook=None, validate=None, reference_probe=None,
                 help=u""):
        self.key = key
        self.group = group
        self.label = label
        self.kind = kind
        self.tier = tier
        self.seed = seed
        self.unit = unit
        self.judging = bool(judging)
        self.storage = storage
        self.owner_view = owner_view
        self.anchor = anchor
        # Dotted names, not callables: the audit tool resolves these to find the
        # accessor a consumer actually calls. A literal key grep cannot see
        # `get_library(portal)` -- which is why WIRING.md needs its "reached
        # through an accessor" section at all.
        self.reader = reader
        self.writer = writer
        self.choices = list(choices or ())
        self.describe_hook = describe_hook
        self.validate = validate
        self.reference_probe = reference_probe
        self.help = help

    @property
    def has_seed(self):
        return self.seed is not NO_SEED

    def __repr__(self):
        return "<Setting {0} ({1}/{2})>".format(
            self.key.encode("ascii", "replace"), self.group, self.tier)


_REGISTRY = {}


def register(setting=None, **kw):
    """Declare a setting. Call at module import time, from its owning module.

    Refuses two things outright rather than reporting them later:

      * a DUPLICATE key -- rule 3 (single source of truth) enforced where
        WIRING.md §1.4 can only report it after the fact;
      * `judging=True` together with a `seed` -- a judging criterion that can
        fall back to a seed silently defeats the refuse-to-judge decision, so
        the combination is a declaration error, not a runtime one.
    """
    s = setting if setting is not None else Setting(**kw)
    if s.key in _REGISTRY:
        raise ValueError(
            "setting {0!r} is already registered (by {1!r}) -- one fact, one "
            "owner".format(s.key, _REGISTRY[s.key].owner_view or "?"))
    if s.group not in GROUPS:
        raise ValueError("setting {0!r}: unknown group {1!r}; expected one of "
                         "{2}".format(s.key, s.group, list(GROUPS)))
    if s.tier not in TIERS:
        raise ValueError("setting {0!r}: unknown tier {1!r}".format(s.key, s.tier))
    if s.kind not in KINDS:
        raise ValueError("setting {0!r}: unknown kind {1!r}".format(s.key, s.kind))
    if s.storage not in STORAGE:
        raise ValueError("setting {0!r}: unknown storage {1!r}".format(
            s.key, s.storage))
    if s.judging and s.has_seed:
        raise ValueError(
            "setting {0!r} is judging AND carries a seed. A criterion that "
            "decides pass/fail must refuse when unset, not substitute a "
            "believable number -- see tests/test_unconfigured_criteria.py"
            .format(s.key))
    if s.storage == STORAGE_LINKED and s.describe_hook is None:
        raise ValueError(
            "setting {0!r} is linked but declares no describe_hook, so the "
            "console cannot show its value".format(s.key))
    _REGISTRY[s.key] = s
    return s


def registered(group=None, tier=None):
    """Declared settings, sorted by group order then key."""
    out = [s for s in _REGISTRY.values()
           if (group is None or s.group == group)
           and (tier is None or s.tier == tier)]
    return sorted(out, key=lambda s: (GROUPS.index(s.group), s.key))


def get_setting(key):
    """The declaration, or None."""
    return _REGISTRY.get(key)


def _clear_registry_for_tests():
    """Only for tests that assert on registration errors."""
    _REGISTRY.clear()


# ── Storage ──────────────────────────────────────────────────────────────────

def _load(portal):
    """{"overrides": {...}, "audit": [...]} -- never raises, never None."""
    empty = {"overrides": {}, "audit": []}
    if portal is None:
        return empty
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(portal).get(ANNOTATION_KEY)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("settings registry unreadable: %s", exc)
        return empty
    if not raw:
        return empty
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        # Same posture as facility_qc: log and fall back to seeds rather than
        # break every page that reads a setting.
        logger.warning("settings registry unparseable; using seeds")
        return empty
    if not isinstance(data, dict):
        return empty
    data.setdefault("overrides", {})
    data.setdefault("audit", [])
    return data


def _store(portal, data):
    from zope.annotation.interfaces import IAnnotations
    data["audit"] = (data.get("audit") or [])[-AUDIT_LIMIT:]
    IAnnotations(portal)[ANNOTATION_KEY] = json.dumps(data)


# ── Coercion and validation ──────────────────────────────────────────────────

def coerce(setting, value):
    """Value as the declared kind. Raises ValueError with a readable message."""
    kind = setting.kind
    if kind == KIND_BOOL:
        if isinstance(value, bool):
            return value
        return _text(value).strip().lower() in (
            u"1", u"true", u"on", u"yes")
    if value in (None, u"", ""):
        # An empty submission means "no value", which for a judging setting is
        # how the lab clears it back to unset.
        return None
    if kind == KIND_FLOAT:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(u"{0} must be a number; got {1!r}".format(
                setting.label or setting.key, value))
    if kind == KIND_INT:
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(u"{0} must be a whole number; got {1!r}".format(
                setting.label or setting.key, value))
    if kind == KIND_LIST:
        if isinstance(value, (list, tuple)):
            return list(value)
        raise ValueError(u"{0} must be a list".format(
            setting.label or setting.key))
    if kind == KIND_CHOICE:
        val = _text(value)
        if setting.choices and val not in setting.choices:
            raise ValueError(u"{0}: {1!r} is not one of {2}".format(
                setting.label or setting.key, val, setting.choices))
        return val
    return _text(value)


# ── Reading ──────────────────────────────────────────────────────────────────

def get(portal, key):
    """The value in force. RAISES UnconfiguredSetting for an unset judging key.

    Override first, seed second. A linked setting delegates to its owner's
    accessor, so there is still exactly one read path per fact.
    """
    s = _REGISTRY.get(key)
    if s is None:
        raise KeyError("setting {0!r} is not registered".format(key))
    if s.storage == STORAGE_LINKED or s.storage == STORAGE_DERIVED:
        described = _describe_linked(portal, s)
        if described["source"] == "unset":
            if s.judging:
                raise UnconfiguredSetting(s.key, s.label, s.owner_view)
            return None
        return described["value"]
    overrides = _load(portal).get("overrides") or {}
    if key in overrides:
        return overrides[key]
    if s.judging:
        raise UnconfiguredSetting(s.key, s.label, s.owner_view)
    return s.seed if s.has_seed else None


def _describe_linked(portal, s):
    """Ask the owning surface. Never raises -- a broken hook must not blank the
    console, it must show as unknown."""
    try:
        result = s.describe_hook(portal, s) or {}
    except Exception as exc:                                # noqa: BLE001
        logger.warning("describe_hook for %s failed: %s", s.key, exc)
        return {"value": None, "seed": None, "source": "unknown",
                "customised": False}
    result.setdefault("value", None)
    result.setdefault("seed", None)
    result.setdefault("source", "unset")
    result.setdefault("customised", result["source"] == "override")
    return result


def describe(portal, key, _data=None):
    """Everything the console needs for one row. NEVER raises.

    `source` is one of: override | seed | unset | derived | unknown.
    `unset` on a judging setting is the status that actually blocks a run, which
    is why it has to be renderable rather than throwable.
    """
    s = _REGISTRY.get(key)
    if s is None:
        return {"key": key, "label": key, "source": "unknown",
                "registered": False}
    row = {
        "key": s.key, "label": s.label, "group": s.group,
        "group_label": GROUP_LABELS.get(s.group, s.group),
        "tier": s.tier, "kind": s.kind, "unit": s.unit,
        "judging": s.judging, "storage": s.storage,
        "owner_view": s.owner_view, "anchor": s.anchor,
        "help": s.help, "registered": True,
        "seed": None if not s.has_seed else s.seed,
        "has_seed": s.has_seed,
    }
    if s.storage == STORAGE_DERIVED:
        described = _describe_linked(portal, s)
        row.update(value=described["value"], source="derived", customised=False)
        return row
    if s.storage == STORAGE_LINKED:
        described = _describe_linked(portal, s)
        row.update(value=described["value"], seed=described["seed"],
                   source=described["source"],
                   customised=described["customised"])
        return row
    overrides = (_data if _data is not None else _load(portal)).get(
        "overrides") or {}
    if s.key in overrides:
        row.update(value=overrides[s.key], source="override", customised=True)
    elif s.has_seed:
        row.update(value=s.seed, source="seed", customised=False)
    else:
        row.update(value=None, source="unset", customised=False)
    return row


def describe_all(portal, group=None, tier=None):
    """One annotation read for every row -- the console must not do N reads."""
    data = _load(portal)
    return [describe(portal, s.key, _data=data)
            for s in registered(group=group, tier=tier)]


def unconfigured(portal):
    """Judging settings with no value. This is the list that blocks runs."""
    return [r for r in describe_all(portal)
            if r.get("judging") and r.get("source") == "unset"]


# ── Writing ──────────────────────────────────────────────────────────────────

def set_value(portal, key, value, actor=None, allowed_tiers=None):
    """Store one override, or clear it when it equals the seed.

    `allowed_tiers` is the caller's authority. The view layer decides who the
    caller is; this refuses to write outside what it was handed, so a missing
    check in one view cannot quietly widen the registry.
    """
    s = _REGISTRY.get(key)
    if s is None:
        raise KeyError("setting {0!r} is not registered".format(key))
    if s.storage != STORAGE_REGISTRY:
        raise ValueError(
            "setting {0!r} is {1}, not registry-owned -- it must be edited in "
            "{2}. Writing it here would make a second owner for one fact."
            .format(key, s.storage, s.owner_view or "its own editor"))
    if allowed_tiers is not None and s.tier not in allowed_tiers:
        raise ValueError(
            "setting {0!r} is in the {1} tier; the caller holds {2}".format(
                key, s.tier, sorted(allowed_tiers)))
    coerced = coerce(s, value)
    if s.validate is not None:
        s.validate(coerced)

    try:   # change history (R1): one trail for every setting
        from senaite.pfas import config_history
        config_history.track(portal, "settings", key,
                             lambda: {"override": _load(portal).get("overrides", {}).get(key)},
                             label=s.label or key)
    except Exception:
        pass
    data = _load(portal)
    overrides = data.setdefault("overrides", {})
    # Only the DIFFERENCE is stored, so a seed correction still reaches a lab
    # that never overrode this value. `save_library`'s trim rule, generalised.
    if s.has_seed and coerced == s.seed:
        removed = overrides.pop(key, None) is not None
        if removed:
            _audit(data, key, coerced, actor, u"reset to default")
            _store(portal, data)
        # True when an override was cleared: the value in force really did move
        # (from the override back to the seed), and a caller that reports "no
        # change" there would be lying to the person who just made one. False
        # only when the setting was already at its default.
        return removed
    if overrides.get(key) == coerced:
        return False
    overrides[key] = coerced
    _audit(data, key, coerced, actor, u"changed")
    _store(portal, data)
    return True


def _audit(data, key, value, actor, what):
    from datetime import datetime
    data.setdefault("audit", []).append({
        "key": key,
        "value": value,
        "actor": actor or u"(unrecorded)",
        "what": what,
        "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    })


def last_changed(portal, key):
    """The newest audit entry for one key, or None."""
    newest = None
    for entry in _load(portal).get("audit") or []:
        if entry.get("key") == key:
            newest = entry
    return newest
