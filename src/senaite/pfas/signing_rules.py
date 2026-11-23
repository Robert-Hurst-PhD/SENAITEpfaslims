# -*- coding: utf-8 -*-
"""The signing rules a manager sets (Lab Settings, System > Signing).

    pin_min, pin_max  how many digits a signing PIN has
    lock_tries        failed signing attempts by one person ...
    lock_minutes      ... within these minutes lock their signing for as long
    expiry_days       days after which a password and a PIN expire; unset,
                      neither expires

The PIN and lock rules are seeded with the values the signing core has always
used; expiry is unset until a manager enters it, so nothing expires on its own.
One expiry serves both: the site has no password schedule of its own.

Pure helpers first; the store imports Plone lazily. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

KEY = "senaite.pfas.signing_rules"
FIELDS = ("pin_min", "pin_max", "lock_tries", "lock_minutes", "expiry_days")
SEEDS = {"pin_min": 6, "pin_max": 12, "lock_tries": 5, "lock_minutes": 15, "expiry_days": None}
# the bounds a manager may set: a PIN of fewer digits than PIN_FLOOR is
# refused, as is one longer than PIN_CEILING
PIN_FLOOR, PIN_CEILING = 4, 32
# (field, form name, lowest, highest, may be blank, refusal)
_FORM = (
    ("pin_min", "sign_pin_min", PIN_FLOOR, PIN_CEILING, False,
     u"The shortest PIN is a whole number of digits from %d to %d." % (PIN_FLOOR, PIN_CEILING)),
    ("pin_max", "sign_pin_max", PIN_FLOOR, PIN_CEILING, False,
     u"The longest PIN is a whole number of digits from %d to %d." % (PIN_FLOOR, PIN_CEILING)),
    ("lock_tries", "sign_lock_tries", 1, None, False,
     u"Wrong tries before a lock is a whole number, 1 or more."),
    ("lock_minutes", "sign_lock_minutes", 1, None, False,
     u"The lock is a whole number of minutes, 1 or more."),
    ("expiry_days", "sign_expiry_days", 1, None, True,
     u"Days before a password or PIN expires is a whole number, 1 or more, or blank."),
)
LONGEST_UNDER_SHORTEST = u"The longest PIN cannot be shorter than the shortest."


def _whole(value):
    try:
        return int(value) if value not in (None, u"", "") and int(value) == float(value) else None
    except (TypeError, ValueError):
        return None


def settings(stored):
    """The rules in force: each stored value that is still a whole number in
    its bounds, else its seed."""
    stored = stored or {}
    out = dict(SEEDS)
    for field, _name, low, high, blank, _why in _FORM:
        value = _whole(stored.get(field))
        if value is None:
            if blank and field in stored:
                out[field] = None
            continue
        if value >= low and (high is None or value <= high):
            out[field] = value
    if out["pin_max"] < out["pin_min"]:
        out["pin_min"], out["pin_max"] = SEEDS["pin_min"], SEEDS["pin_max"]
    return out


def from_form(form):
    """(rules, errors) from the System form; nothing is saved while any
    value is refused."""
    out, errors = {}, []
    for field, name, low, high, blank, why in _FORM:
        raw = (u"%s" % (form.get(name) or u"")).strip()
        if not raw and blank:
            out[field] = None
            continue
        value = _whole(raw)
        if value is None or value < low or (high is not None and value > high):
            errors.append(why)
            continue
        out[field] = value
    if not errors and out["pin_max"] < out["pin_min"]:
        errors.append(LONGEST_UNDER_SHORTEST)
    return out, errors


def lock_seconds(rules):
    return int((rules or SEEDS).get("lock_minutes") or SEEDS["lock_minutes"]) * 60


# ── storage (Plone) ─────────────────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    try:
        return settings(json.loads(_ann(portal).get(KEY) or "{}"))
    except ValueError:
        return settings({})


def save(portal, values):
    _ann(portal)[KEY] = json.dumps(dict((k, values.get(k)) for k in FIELDS), sort_keys=True)
