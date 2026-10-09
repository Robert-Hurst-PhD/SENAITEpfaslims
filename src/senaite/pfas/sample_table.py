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
    seed_sample_capture(profile)          -> True when stages were given the key
    processing_stage(stages)              -> the stage that is the Sample
                                             Processing Log (FM-ENV-004)
    seed_processing_checks(profile)       -> True when the processing stage
                                             was given its checks key

Spikes are not recorded here any more: an extraction batch's QC and each
one's parent and level are its members (extraction_batch.py); older `spikes` rows are read by dilution_ref.spikes_from_rows.

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
            # older rows (the Run Builder's) name the column `matrix`
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
    try:
        from senaite.pfas.dilution_ref import parse_factor
    except ImportError:                                     # tests: plain import path
        from dilution_ref import parse_factor
    return parse_factor(text) is not None


def append_dilution(rows, parent, injection, factor, by, at):
    """Append one dilution. Refused (rows unchanged, reason given) without a
    parent, an injection name or a usable factor, or when the injection name
    is already a sample or a logged dilution."""
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
    rows.append({"sample_id": injection, "dilution_of": parent,
                 "dilution_factor": (u"%s" % factor).strip(),
                 "logged_by": by or u"", "logged_at": at or u""})
    return rows, u""


def dilutions(rows):
    return [r for r in rows or [] if isinstance(r, dict) and _is_dilution(r)]


def seed_sample_capture(profile):
    """Give every stage the key once: the test-portion stage ("weigh",
    "aliquot mass", "sample loading") records the sample amount, the
    reconstitution stage the final volume; the lab can change either in the
    stage editor."""
    changed = False
    for st in (profile or {}).get("extraction_stages") or []:
        if STAGE_KEY in st:
            continue
        text = u"{0} {1}".format(st.get("name") or u"", st.get("description") or u"").lower()
        if any(w in text for w in (u"weigh", u"aliquot mass", u"sample loading")):
            st[STAGE_KEY] = u"amount"
        elif u"reconstitut" in text:
            st[STAGE_KEY] = u"final_volume"
        else:
            st[STAGE_KEY] = u""
        changed = True
    return changed


def processing_stage(stages):
    """The stage where the test portion is taken -- the first one recording
    the sample amount. It is the Sample Processing Log, FM-ENV-004 (2026-10-06: the guided extraction is the one record of homogenising and
    weighing out aliquots), or None when the method has no such stage."""
    for st in sorted(stages or [], key=lambda s: s.get("order", 0)):
        if capture_column(st) == AMOUNT:
            return st
    return None


# FM-ENV-004's grinder check was carried to the processing stage on
# 2026-10-06 and removed the same day: each sample's homogenisation record
# confirms its homogeniser was cleaned, per unit and per use.
GRINDER_CHECK = u"Grinder cleaned / blank passed"


CHECKS_MARK = u"processing_checks_v"     # profile key: this migration ran


def seed_processing_checks(profile):
    """Once per method: the processing stage gets an empty `confirmations`
    (the lab adds checks in the stage editor), and the grinder check seeded
    earlier is taken off it. Marked on the profile so a check the lab adds
    back later is never taken off again."""
    profile = profile if profile is not None else {}
    if profile.get(CHECKS_MARK) == 2:
        return False
    st = processing_stage(profile.get("extraction_stages"))
    if st is not None:
        st[u"confirmations"] = [c for c in st.get(u"confirmations") or [] if c != GRINDER_CHECK]
    profile[CHECKS_MARK] = 2
    return True
