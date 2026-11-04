# -*- coding: utf-8 -*-
"""Derive the accreditation / non-conformance disclosure from a frozen
worksheet snapshot.

Data that does not conform may always be output; it is qualified as not under
accreditation (non-compliance), stating exactly how it non-conforms. So nothing
here refuses: it returns a status and a specific statement ("LFSM acceptance
40-140% per the project QAPP, where EPA 1633A Table 8 requires 50-130%").

Derived, never authored: the resolution that produced the results already
records every departure (key, displacing tier and document revision, the
method's value, how far each end moved). This module only reads and formats.

What it never says:

  * that a sample IS accredited. Scope is the lab's scope of accreditation;
    this module can only establish that something fell OUT of scope.
  * "conforms" for "no departure detected": a criterion without a
    published-method baseline resolves UNKNOWN, not passed.
  * anything from live criteria when there is no snapshot: that is "not
    recorded", never what the lab would do now.

Pure and Zope-free (plain dicts in and out), so the standalone harness runs it
under python3 like ruleset.resolve().
"""
from __future__ import absolute_import, unicode_literals

# Snapshot statuses (senaite.pfas.worksheet_criteria_snapshot)
_SNAP_FROZEN = u"frozen"

# Per-criterion conformance verdicts (senaite.pfas.method_baselines)
_DEPARTS = u"DEPARTS"
_UNKNOWN = u"UNKNOWN"
_CONFORMS = u"CONFORMS"

# Disclosure outcomes
NOT_RECORDED = u"not_recorded"
DEPARTS_FROM_METHOD = u"departs_from_method"
NO_DEPARTURE_DETECTED = u"no_departure_detected"
FULLY_COMPARED = u"fully_compared"


def _departure_items(rows):
    """One flat item per departing criterion, with the method's value beside
    the project's so a reader can see what changed and by how much."""
    items = []
    for row in rows or []:
        if row.get(u"conformance") != _DEPARTS:
            continue
        dep = row.get(u"departure") or {}
        items.append({
            u"key": row.get(u"key"),
            u"analyte": row.get(u"analyte"),
            u"tier": row.get(u"tier"),
            u"source_doc": row.get(u"source_doc"),
            u"source_rev": row.get(u"source_rev"),
            u"applied_value": dep.get(u"resolved_value", row.get(u"value")),
            u"method_value": dep.get(u"baseline_value"),
            u"citation": dep.get(u"citation"),
            u"ends": dep.get(u"ends") or [],
        })
    return items


def build_disclosure(snapshot):
    """Turn a frozen worksheet snapshot into the disclosure for a certificate.

    `snapshot` is whatever `worksheet_criteria_snapshot.get_frozen_criteria()`
    returned -- a payload dict, or None.

    Returns a dict with:
      outcome            one of the four module constants
      in_scope_claimed   ALWAYS False. See the module docstring: this module
                         can take a sample out of scope, never put one in.
      out_of_scope       True only when at least one criterion departed
      items              the itemised departures (empty unless out_of_scope)
      uncompared         how many criteria had no baseline to compare against
      compared           how many did
      reason             why, in one line, when there is nothing to itemise
      batch_id / method_id / matrix / frozen_at   carried through when known
    """
    base = {
        u"in_scope_claimed": False,
        u"out_of_scope": False,
        u"items": [],
        u"compared": 0,
        u"uncompared": 0,
        u"batch_id": None,
        u"method_id": None,
        u"matrix": None,
        u"frozen_at": None,
        u"reason": None,
    }

    if not snapshot:
        base.update({
            u"outcome": NOT_RECORDED,
            u"reason": (u"No criteria were recorded for this worksheet at "
                        u"verification, so what governed these results cannot "
                        u"be stated."),
        })
        return base

    base.update({
        u"batch_id": snapshot.get(u"batch_id"),
        u"method_id": snapshot.get(u"method_id"),
        u"matrix": snapshot.get(u"matrix"),
        u"frozen_at": snapshot.get(u"frozen_at"),
    })

    status = snapshot.get(u"status")
    if status != _SNAP_FROZEN:
        # "unresolved" / "failed" are markers that resolution did not produce a
        # judgement basis. They are NOT an absence of departures.
        base.update({
            u"outcome": NOT_RECORDED,
            u"reason": (u"Criteria were not resolved at verification "
                        u"(recorded as '{0}'), so no departure can be stated "
                        u"either way.").format(status or u"unknown"),
        })
        return base

    rows = snapshot.get(u"criteria") or []
    items = _departure_items(rows)
    compared = len([r for r in rows
                    if r.get(u"conformance") in (_DEPARTS, _CONFORMS)])
    uncompared = len([r for r in rows
                      if r.get(u"conformance") == _UNKNOWN])
    base.update({u"compared": compared, u"uncompared": uncompared})

    if items:
        base.update({
            u"outcome": DEPARTS_FROM_METHOD,
            u"out_of_scope": True,
            u"items": items,
        })
        return base

    if uncompared:
        base.update({
            u"outcome": NO_DEPARTURE_DETECTED,
            u"reason": (u"No departure from a published method requirement was "
                        u"detected. {0} of {1} criteria had no published-method "
                        u"baseline to compare against, so conformance is not "
                        u"established for those.").format(
                            uncompared, len(rows)),
        })
        return base

    base.update({
        u"outcome": FULLY_COMPARED,
        u"reason": (u"Every recorded criterion was compared against a "
                    u"published-method baseline and none departed."),
    })
    return base


def format_value(value):
    """A criterion value as a reader should see it.

    Window criteria travel as {"min": x, "max": y}; a dict must never print
    as a Python repr on a client document.

    Renders a window as "5.0-130.0", a half-open window as ">= 5.0" or
    "<= 130.0", a boolean as required/not required, and anything else as itself.
    """
    if isinstance(value, dict):
        lo = value.get(u"min")
        hi = value.get(u"max")
        if lo is not None and hi is not None:
            return u"{0}-{1}".format(lo, hi)
        if lo is not None:
            return u">= {0}".format(lo)
        if hi is not None:
            return u"<= {0}".format(hi)
        return u"not specified"
    if value is True:
        return u"required"
    if value is False:
        return u"not required"
    if value is None:
        return u"not specified"
    return u"{0}".format(value)


def format_departure(item):
    """One human-readable line for a departing criterion.

    Names the applied value, the method's value, and the document revision
    that displaced it: a reader must tell WHAT was different and BY HOW MUCH.
    """
    key = item.get(u"key") or u"criterion"
    analyte = item.get(u"analyte")
    subject = u"{0} ({1})".format(key, analyte) if analyte else key

    doc = item.get(u"source_doc")
    rev = item.get(u"source_rev")
    if doc and rev is not None:
        authority = u"{0} rev {1}".format(doc, rev)
    elif doc:
        authority = u"{0}".format(doc)
    else:
        # The lab tier may have no document reference (the method profile
        # carries values with no link to a QAM or SOP revision): say so,
        # never invent one.
        authority = u"the lab's configured value (no controlled document "\
                    u"recorded)"

    line = u"{0}: {1} applied per {2}, where the method requires {3}".format(
        subject, format_value(item.get(u"applied_value")), authority,
        format_value(item.get(u"method_value")))

    ends = item.get(u"ends") or []
    details = [e.get(u"detail") for e in ends if e.get(u"detail")]
    if details:
        line = u"{0} ({1})".format(line, u"; ".join(details))

    citation = item.get(u"citation")
    if citation:
        line = u"{0} [{1}]".format(line, citation)
    return line
