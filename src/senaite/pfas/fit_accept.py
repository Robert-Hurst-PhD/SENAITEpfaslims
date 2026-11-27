# -*- coding: utf-8 -*-
"""The score a fit must reach to be accepted (Lab Settings, System > Fit score).

A method may set its own "Score to accept a fit" (1 to 100); blank uses the
lab's, which reads DEFAULT until a manager enters another number. The score
colours the review's badge; it gates nothing.

Pure helpers first; the store imports Plone lazily. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

KEY = "senaite.pfas.fit_accept"
DEFAULT = 85
LOWEST, HIGHEST = 1, 100
REFUSAL = u"The score to accept a fit is a whole number from %d to %d." % (LOWEST, HIGHEST)


def whole(value):
    """The whole number from LOWEST to HIGHEST that `value` holds, else None.
    A bool, a fraction and a number outside the bounds hold none."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        text = (u"%s" % value).strip()
        number = int(float(text)) if text else None
        if number is None or number != float(text):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return number if LOWEST <= number <= HIGHEST else None


def lab_default(stored):
    """The lab's score: the stored whole number in bounds, else DEFAULT."""
    return whole((stored or {}).get("default")) or DEFAULT


def from_form(form):
    """(values, errors) from the System form; blank resets to the default."""
    raw = (u"%s" % (form.get("fit_accept_default") or u"")).strip()
    if not raw:
        return {"default": None}, []
    value = whole(raw)
    if value is None:
        return {}, [REFUSAL]
    return {"default": value}, []


# ── storage (Plone) ─────────────────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def stored(portal):
    try:
        return json.loads(_ann(portal).get(KEY) or "{}")
    except ValueError:
        return {}


def load(portal):
    """The lab's score in force."""
    return lab_default(stored(portal))


def save(portal, values):
    _ann(portal)[KEY] = json.dumps({"default": whole(values.get("default"))}, sort_keys=True)
