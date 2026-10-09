# -*- coding: utf-8 -*-
"""What the Run Builder decides before it builds a sequence. Pure; Python 2.7 and 3.

    curve_decision(profile, last_curve, today)
        Does this run carry a new calibration curve? The method profile says
        when one is needed (Calibration & CCV: "A new curve is run", "A curve
        may be reused for"); otherwise the bench chemist is asked. A curve that
        is not approved, or older than the limit, is never reused.

    opening(seq, new_curve, profile)
        The run template's tokens with the calibration and its verification
        set for that decision: a new curve runs the ladder and (unless the
        profile says not) an ICV; a reused curve skips the ladder and opens
        with the profile's check (a CCV unless it says ICV).

    export_rows(rows, columns)
        The instrument's sample list: one row per injection, columns as the
        method's run template lists them ([header, source]); the Waters
        MassLynx starter is MASSLYNX_COLUMNS.
"""
from __future__ import absolute_import, unicode_literals

from datetime import datetime

NEW, REUSE = u"new", u"reuse"


def _days(a, b):
    try:
        return (datetime.strptime(b[:10], "%Y-%m-%d") - datetime.strptime(a[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def curve_decision(profile, last_curve, today):
    """{"ask", "forced", "default", "reason"}: `forced` is the only answer the
    run may take (new or None); `ask` whether the bench chemist chooses."""
    iv = (profile or {}).get("instrument_verification") or {}
    cal = iv.get("calibration") or {}
    policy = cal.get("new_curve") or u""
    try:
        max_age = int(cal.get("max_age_days")) if cal.get("max_age_days") not in (None, u"") else None
    except (TypeError, ValueError):
        max_age = None
    if policy == u"every_run":
        return {"ask": False, "forced": NEW, "default": NEW,
                "reason": u"the method runs a new curve in every run"}
    if not last_curve:
        return {"ask": False, "forced": NEW, "default": NEW,
                "reason": u"no curve on record for this method"}
    status = (last_curve.get("status") or u"").lower()
    if status != u"approved":
        return {"ask": False, "forced": NEW, "default": NEW,
                "reason": u"the last curve (%s) is %s, not approved"
                          % (last_curve.get("run_date") or u"?", status or u"not reviewed")}
    age = _days(last_curve.get("run_date") or u"", today)
    if max_age is not None and (age is None or age > max_age):
        return {"ask": False, "forced": NEW, "default": NEW,
                "reason": u"the last curve is %s days old; the method allows %d"
                          % (age if age is not None else u"?", max_age)}
    return {"ask": True, "forced": None,
            "default": REUSE if policy == u"when_due" else None,
            "reason": u"the last curve (%s) is approved%s" % (
                last_curve.get("run_date") or u"?",
                u", %d days old" % age if age is not None and age >= 0 else u"")}


def opening(seq, new_curve, profile):
    """The template's tokens for this run's calibration decision."""
    iv = (profile or {}).get("instrument_verification") or {}
    icv = iv.get("icv") or {}
    seq = [t for t in seq or []]
    if new_curve:
        if u"CAL" not in seq:
            seq.insert(0, u"CAL")
        if (icv.get("after_new_curve") or u"") == u"no":
            return [t for t in seq if t != u"ICV"]
        if u"ICV" not in seq:
            seq.insert(seq.index(u"CAL") + 1, u"ICV")
        return seq
    check = u"ICV" if (icv.get("when_reused") or u"") == u"ICV" else u"CCV"
    seq = [t for t in seq if t not in (u"CAL", u"ICV")]
    return [check] + seq


# The Waters MassLynx sample list: the column identifiers its
# sample-list import reads. A STARTER: the lab checks it against its MassLynx
# version and edits it in the method's run template (MS / inlet method files
# and the injection volume are the lab's own).
MASSLYNX_COLUMNS = [
    [u"FILE_NAME", u"name"],
    [u"FILE_TEXT", u"description"],
    [u"SAMPLE_LOCATION", u"vial"],
    [u"TYPE", u"masslynx-type"],
    [u"LEVEL", u"level"],
    [u"MS_FILE", u"fixed:"],
    [u"INLET_FILE", u"fixed:"],
    [u"INJ_VOL", u"fixed:"],
]
SOURCES = (u"name", u"description", u"vial", u"type", u"masslynx-type", u"level")
_MASSLYNX_TYPE = {u"Sample": u"Analyte", u"Standard": u"Standard", u"QC": u"QC", u"Blank": u"Blank"}


def export_rows(rows, columns):
    """[[header, ...], [value, ...], ...] for the sequence `rows`
    ([{"vial", "name", "type", "description", "level"?}])."""
    columns = [c for c in columns or MASSLYNX_COLUMNS if c and (c[0] or u"").strip()]
    out = [[c[0] for c in columns]]
    for r in rows:
        line = []
        for _h, src in columns:
            src = src or u""
            if src.startswith(u"fixed:"):
                line.append(src[len(u"fixed:"):])
            elif src == u"masslynx-type":
                line.append(_MASSLYNX_TYPE.get(r.get("type") or u"", r.get("type") or u""))
            else:
                line.append(u"%s" % (r.get(src) if r.get(src) is not None else u""))
        out.append(line)
    return out


def place_members(seq, qc_members, samples_token=u"SAMPLES"):
    """The template's tokens with the extraction batch's QC placed: a token
    whose role the batch holds is played by its members (in order); member
    roles the template has no token for go straight after the samples, so
    every member is injected. Returns [(token, member injection or None)]."""
    out, used = [], set()
    for tok in seq:
        role = tok.upper()
        if role in qc_members and tok != samples_token:
            for inj in qc_members[role]:
                out.append((tok, inj))
            used.add(role)
            continue
        out.append((tok, None))
        if tok == samples_token:
            for r in sorted(qc_members):
                if r not in used and r not in [t.upper() for t in seq]:
                    for inj in qc_members[r]:
                        out.append((r, inj))
                    used.add(r)
    return out
