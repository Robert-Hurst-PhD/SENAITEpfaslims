# -*- coding: utf-8 -*-
"""The per-sample table the guided extraction records into FM-ENV-003's
`samples` rows -- the table the pipeline already reads -- and the dilution
log ("Form numbers, per-sample correction, dilutions").

A sample row: sample_id, matrix_type, and what the bench measured --
`amount` + `amount_unit` (g for a solid, mL for a water) at the stage that
takes the test portion, `final_volume_ml` at reconstitution. Other columns
(sample_type, spike_amount_ng, ...) are kept as they are.

A dilution row: `dilution_of` (the sample re-injected), `sample_id` (the
dilution's injection name), `dilution_factor`, `logged_by`, `logged_at`.
Dilutions are APPENDED, never edited: a dilution is a fact about what was
re-injected, and the record of it must not change after the result exists.

    capture_column(stage)                 -> "amount" | "final_volume_ml" | "spe_port" | ""
    merge_ports(ports, edits)             -> {injection: port}
    port_warnings(edits)                  -> ["needs a note", ...]
    rows_for_card(rows, batch_samples)    -> the sample rows to show
    merge_samples(rows, edits, column)    -> rows with the column recorded
    missing(rows, edits, column)          -> sample ids with no value
    append_dilution(rows, parent, injection, factor, by, at) -> (rows, error)
    processing_stage(stages)              -> the stage that is the Sample
                                             Processing Log (FM-ENV-004)

Spikes are not recorded here: an extraction batch's QC and each one's
parent and level are its members (extraction_batch.py); FM-ENV-003 `spikes`
rows are read by dilution_ref.spikes_from_rows.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals


AMOUNT, FINAL_VOLUME = u"amount", u"final_volume_ml"
# the SPE manifold port each member was loaded on: every
# member, samples and QC, at the stage the method's logbook marks. Kept
# beside the rows (log["spe_ports"] = {injection: port}), not in them: the
# pipeline reads the rows as samples, and a QC is not one.
SPE_PORT = u"spe_port"
STAGE_KEY = "captures_samples"
_STAGE_VALUES = {u"amount": AMOUNT, u"final_volume": FINAL_VOLUME, u"spe_port": SPE_PORT}


def capture_column(stage):
    return _STAGE_VALUES.get((stage or {}).get(STAGE_KEY) or u"", u"")


def _is_dilution(row):
    return bool((row.get("dilution_of") or u"").strip())


def default_unit(matrix):
    return u"mL" if u"water" in (matrix or u"").lower() else u"g"


def rows_for_card(rows, batch_samples):
    """Recorded sample rows first, then the batch's samples not yet listed
    (`batch_samples` = [{"sample_id", "matrix"}])."""
    out, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict) or _is_dilution(r):
            continue
        sid = (r.get("sample_id") or u"").strip()
        if sid and sid not in seen:
            seen.add(sid)
            row = dict(r)
            # a Run Builder row names the column `matrix`
            row["matrix_type"] = r.get("matrix_type") or r.get("matrix") or u""
            out.append(row)
    for s in batch_samples or []:
        sid = (s.get("sample_id") or u"").strip()
        if sid and sid not in seen:
            seen.add(sid)
            out.append({"sample_id": sid, "matrix_type": s.get("matrix") or u"",
                        "amount_unit": default_unit(s.get("matrix"))})
    return out


def _clean(value):
    v = (u"%s" % value).strip() if value is not None else u""
    try:
        float(v)
        return v
    except ValueError:
        return u""


def merge_samples(rows, edits, column):
    """Record one column for each edited sample row; a new sample id becomes
    a new row; dilution rows and every other column are left alone.
    `edits` = [{"sample_id", "value", "unit"?, "matrix_type"?}]."""
    out = [dict(r) for r in rows or [] if isinstance(r, dict)]
    index = dict(((r.get("sample_id") or u"").strip(), r) for r in out
                 if not _is_dilution(r) and (r.get("sample_id") or u"").strip())
    diluted = set((r.get("sample_id") or u"").strip() for r in out if _is_dilution(r))
    for e in edits or []:
        sid = (e.get("sample_id") or u"").strip()
        # a dilution is the same extract re-injected: it has no amount of its own
        if not sid or sid in diluted or column not in (AMOUNT, FINAL_VOLUME):
            continue
        row = index.get(sid)
        if row is None:
            row = {"sample_id": sid, "matrix_type": e.get("matrix_type") or u""}
            out.append(row)
            index[sid] = row
        row[column] = _clean(e.get("value"))
        if column == AMOUNT:
            row["amount_unit"] = e.get("unit") or row.get("amount_unit") or \
                default_unit(row.get("matrix_type") or row.get("matrix"))
    return out


def missing(rows, edits, column):
    """The sample ids in this stage's table with no value for its column."""
    return [(e.get("sample_id") or u"").strip() for e in edits or []
            if (e.get("sample_id") or u"").strip() and not _clean(e.get("value"))]


def merge_ports(ports, edits):
    """Record each edited member's SPE port; a blank clears it.
    `edits` = [{"sample_id": injection, "value": port}]."""
    out = dict(ports or {})
    for e in edits or []:
        sid = (e.get("sample_id") or u"").strip()
        if not sid:
            continue
        port = (u"%s" % (e.get("value") or u"")).strip()
        if port:
            out[sid] = port
        else:
            out.pop(sid, None)
    return out


def port_warnings(edits):
    """What the stage's deviation note must explain: a member with no port,
    and a port given to more than one member."""
    out, used = [], {}
    for e in edits or []:
        sid = (e.get("sample_id") or u"").strip()
        port = (u"%s" % (e.get("value") or u"")).strip()
        if not sid:
            continue
        if not port:
            out.append(u"%s: no SPE port recorded" % sid)
        else:
            used.setdefault(port.upper(), []).append(sid)
    for port, who in sorted(used.items()):
        if len(who) > 1:
            out.append(u"SPE port %s: used by %s" % (port, u", ".join(who)))
    return out


def _factor_ok(text):
    """The one rule for a fold (dilution_ref.parse_factor)."""
    from senaite.pfas.dilution_ref import parse_factor
    return parse_factor(text) is not None


def _routes():
    from senaite.pfas.method_profile_sections import DILUTION_ROUTES
    return DILUTION_ROUTES


def route_key(route):
    """A route's key from its key or its label; blank = the extract diluted."""
    text = (u"%s" % (route or u"")).strip()
    for key, label in _routes():
        if text in (key, label):
            return key
    return text or u"extract"


def _num(text):
    try:
        return float(u"%s" % text)
    except (TypeError, ValueError):
        return None


def plan_problem(fold, route, settings):
    """Why a planned dilution is refused by the method's dilution settings
    (the route it allows, its largest dilution), or u"". Unset checks nothing."""
    route = route_key(route)
    if route not in ((settings or {}).get("routes") or [u"extract"]):
        return u"%s is not a route this method allows." % dict(_routes()).get(route, route)
    cap = (settings or {}).get("max_fold")
    if cap not in (None, u"") and (_num(fold) or 0) > float(cap):
        return u"The largest dilution this method allows is %s-fold." % _fmt(cap)
    return u""


def _route_problem(fold, route, aliquot, approval, settings):
    """Why the method's dilution settings refuse this dilution, or u"".
    An unset limit checks nothing."""
    problem = plan_problem(fold, route, settings)
    if problem:
        return problem
    if route == u"reprep":
        amount = _num(aliquot)
        if amount is None or amount <= 0:
            return u"Give the aliquot taken for the re-prep, in mL or g."
        least = settings.get("min_aliquot")
        if least not in (None, u"") and amount < float(least):
            return u"The smallest aliquot for a re-prep is %s." % _fmt(least)
        if settings.get("client_approval") and not (approval or u"").strip():
            return u"A smaller aliquot needs the client's approval: say who approved it and when."
    return u""


def _fmt(v):
    v = float(v)
    return u"%d" % v if v == int(v) else u"%s" % v


def append_dilution(rows, parent, injection, factor, by, at, route=u"", aliquot=None, approval=u"",
                    settings=None):
    """Append one dilution. Refused (rows unchanged, reason given) without a
    parent, an injection name or a usable factor, or when the injection name
    is already a sample or a logged dilution; with the method's dilution
    settings (method_profile_sections.dilution_settings), a route it does not
    allow or a fold, aliquot or approval its limits refuse."""
    parent, injection = (parent or u"").strip(), (injection or u"").strip()
    rows = [dict(r) for r in rows or [] if isinstance(r, dict)]
    if not parent:
        return rows, u"Say which sample was diluted."
    if not injection:
        return rows, u"Give the dilution's injection name, as it appears in the run."
    if not _factor_ok(factor):
        return rows, u"Give the dilution as its total fold, a number above 1 (e.g. 2 or 10); ratios are not accepted."
    if any((r.get("sample_id") or u"").strip() == injection for r in rows):
        return rows, u"{0} is already in the record.".format(injection)
    key = route_key(route)
    if settings is not None:
        problem = _route_problem(factor, key, aliquot, approval, settings)
        if problem:
            return [dict(r) for r in rows], problem
    row = {"sample_id": injection, "dilution_of": parent,
           "dilution_factor": (u"%s" % factor).strip(), "route": dict(_routes()).get(key, key),
           "logged_by": by or u"", "logged_at": at or u""}
    if (u"%s" % (aliquot or u"")).strip():
        row["aliquot"] = (u"%s" % aliquot).strip()
    if (approval or u"").strip():
        row["approval"] = approval.strip()
    rows.append(row)
    return rows, u""


def dilutions(rows):
    return [r for r in rows or [] if isinstance(r, dict) and _is_dilution(r)]


def processing_stage(stages):
    """The stage where the test portion is taken -- the first one recording
    the sample amount. It is the Sample Processing Log, FM-ENV-004 (the
    guided extraction is the one record of homogenising and weighing out
    aliquots), or None when the method has no such stage."""
    for st in sorted(stages or [], key=lambda s: s.get("order", 0)):
        if capture_column(st) == AMOUNT:
            return st
    return None


