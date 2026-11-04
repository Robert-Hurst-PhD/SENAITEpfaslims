# -*- coding: utf-8 -*-
"""One declared list of every lab-owned setting.

A setting registers itself in the module that declares it
(settings_adapters), so the Lab Settings console and the audit enumerate the
SAME list. Each value lives with the editor that owns it (the method
profile, a vocabulary, a store): a setting here is a pointer to it, with a
`describe_hook(portal, setting)` that reports the value in force. The
console lists and links; it never writes, so no fact gets a second owner.

    register(**kw) / registered(group, tier) / get_setting(key)
    describe(portal, key) / describe_all(portal, group, tier)   never raise
    unconfigured(portal)       the judging settings with no value

A judging setting with no value is listed, never given a substitute: a run
judged by it refuses (tests/test_unconfigured_criteria.py).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.settings_registry")

# Who may change a setting. Manager/LabManager/Owner own lab VALUES; the
# structural tier is narrower because withdrawing a vocabulary term or changing a
# form's field schema can orphan records that already reference it.
TIER_LAB = u"lab"
TIER_STRUCTURAL = u"structural"
TIERS = (TIER_LAB, TIER_STRUCTURAL)

# The lab owner's four categories, id and heading together, in display order.
GROUP_QC_LIMITS = u"qc_limits"
GROUP_VOCABULARY = u"vocabulary"
GROUP_WORDING = u"wording"
GROUP_THRESHOLDS = u"thresholds"
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


class Setting(object):
    """One declared setting. See `register()` for the contract."""

    def __init__(self, key, group, label, kind, tier, describe_hook,
                 unit=u"", judging=False, owner_view=u"", anchor=u"", help=u""):
        self.key = key
        self.group = group
        self.label = label
        self.kind = kind
        self.tier = tier
        self.describe_hook = describe_hook
        self.unit = unit
        self.judging = bool(judging)
        self.owner_view = owner_view
        self.anchor = anchor
        self.help = help

    def __repr__(self):
        return "<Setting {0} ({1}/{2})>".format(
            self.key.encode("ascii", "replace"), self.group, self.tier)


_REGISTRY = {}


def register(setting=None, **kw):
    """Declare a setting at import time. A duplicate key, an unknown group,
    tier or kind, or no describe_hook is refused here, not reported later."""
    s = setting if setting is not None else Setting(**kw)
    if s.key in _REGISTRY:
        raise ValueError(
            "setting {0!r} is already registered (by {1!r}): one fact, one "
            "owner".format(s.key, _REGISTRY[s.key].owner_view or "?"))
    if s.group not in GROUPS:
        raise ValueError("setting {0!r}: unknown group {1!r}; expected one of "
                         "{2}".format(s.key, s.group, list(GROUPS)))
    if s.tier not in TIERS:
        raise ValueError("setting {0!r}: unknown tier {1!r}".format(s.key, s.tier))
    if s.kind not in KINDS:
        raise ValueError("setting {0!r}: unknown kind {1!r}".format(s.key, s.kind))
    if s.describe_hook is None:
        raise ValueError(
            "setting {0!r} declares no describe_hook, so the console cannot "
            "show its value".format(s.key))
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


def _described(portal, s):
    """Ask the owning surface. Never raises: a broken hook shows as unknown
    rather than blanking the console."""
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


def describe(portal, key):
    """Everything the console needs for one row. NEVER raises.

    `source` is one of: override | seed | unset | derived | unknown. `unset`
    on a judging setting is what blocks a run, so it has to be renderable.
    """
    s = _REGISTRY.get(key)
    if s is None:
        return {"key": key, "label": key, "source": "unknown",
                "registered": False}
    d = _described(portal, s)
    source = d["source"]
    if source == "seed" and d["seed"] is None and d["value"] in (None, u""):
        source = "unset"            # a default with no default value is unset
    return {
        "key": s.key, "label": s.label, "group": s.group,
        "group_label": GROUP_LABELS.get(s.group, s.group),
        "tier": s.tier, "kind": s.kind, "unit": s.unit,
        "judging": s.judging, "owner_view": s.owner_view, "anchor": s.anchor,
        "help": s.help, "registered": True,
        "value": d["value"], "seed": d["seed"], "has_seed": d["seed"] is not None,
        "source": source, "customised": d["customised"],
    }


def describe_all(portal, group=None, tier=None):
    return [describe(portal, s.key) for s in registered(group=group, tier=tier)]


def unconfigured(portal):
    """Judging settings with no value. This is the list that blocks runs."""
    return [r for r in describe_all(portal)
            if r.get("judging") and r.get("source") == "unset"]
