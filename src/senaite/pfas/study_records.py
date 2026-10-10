# -*- coding: utf-8 -*-
"""Method study records.

One record per study, in a portal annotation (one owner; ZODB transactions), as JSON:

    {"id": "MS-0001", "kind": "mdl" | "mrl" | "pa" | "dl", "method",
     "matrix", "title", "level" (the LFB spike level's label), "fortified",
     "since", "until", "worksheets": [...], "exclusions": [{"injection",
     "analyte", "reason", "by", "at"}], "status": "draft" | "approved" |
     "superseded", "created_by", "created_at", "approved_by",
     "approved_at", "statement", "results": {keyword: {...}} (frozen at
     approval), "applied": {keyword: {"mdl" | "rl": value}}, "file"}

A study is edited while a draft; approval freezes its results, applies them
to the method profile (study_data.applied_values) and freezes the packet
PDF; an approved study of the same kind, method and matrix is superseded.
Pure helpers + a thin storage shell. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json

KEY = "senaite.pfas.method_studies"
DRAFT, APPROVED, SUPERSEDED = u"draft", u"approved", u"superseded"


MDL_DUE_MONTHS = 13      # 40 CFR 136 App. B Rev. 2 4(f): at least every 13 months


def _plus_months(iso_day, months):
    y, m, d = (int(x) for x in iso_day[:10].split("-"))
    m += months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    days = [31, 29 if (y % 4 == 0 and (y % 100 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return u"%04d-%02d-%02d" % (y, m, min(d, days))


def mdl_due(records, today):
    """[{method, matrix, approved, due, overdue}] for every method x matrix
    with an approved annual MDL study (the latest one), oldest due first."""
    latest = {}
    for r in records or []:
        if r.get("kind") != "mdl" or r.get("status") != APPROVED or not r.get("approved_at"):
            continue
        key = (r.get("method"), r.get("matrix"))
        if key not in latest or r["approved_at"] > latest[key]:
            latest[key] = r["approved_at"]
    out = []
    for (method, matrix), at in latest.items():
        due = _plus_months(at, MDL_DUE_MONTHS)
        out.append({"method": method, "matrix": matrix, "approved": at[:10],
                    "due": due, "overdue": due < (today or u"")[:10]})
    return sorted(out, key=lambda e: e["due"])


def chart_hidden(records):
    """The worksheets of every study that has not opted into the control
    charts and blank history (`in_charts`, off by default; lab, 2026-10-09:
    study runs are kept apart from routine data)."""
    out = set()
    for r in records or []:
        if r.get("in_charts"):
            continue
        out.update(r.get("worksheets") or [])
        for p in r.get("parts") or []:
            out.update(p.get("worksheets") or [])
    return out


def next_id(records):
    nums = [int(r["id"].split("-")[1]) for r in records if r.get("id", u"").startswith(u"MS-")]
    return u"MS-%04d" % (max(nums or [0]) + 1)


def new(records, kind, method, matrix, by, at, **params):
    rec = {"id": next_id(records), "kind": kind, "method": method, "matrix": matrix,
           "status": DRAFT, "created_by": by, "created_at": at, "exclusions": [],
           "worksheets": [], "levels": [], "fortified": None, "since": u"", "until": u"",
           "title": u"", "reference_materials": [], "pt": {}}
    rec.update(dict((k, v) for k, v in params.items() if k in rec or k in ("title",)))
    return rec


def normalise(rec):
    """Records from before 2026-10-09 named one `level`; now `levels`."""
    if "levels" not in rec:
        rec["levels"] = [rec["level"]] if rec.get("level") else []
    rec.pop("level", None)
    rec.setdefault("reference_materials", [])
    rec.setdefault("pt", {})
    return rec


def exclude(rec, injection, analyte, reason, by, at):
    """A documented exclusion; refused without a reason (App. B Rev. 2
    §2(b): the rationale must be documented)."""
    if rec.get("status") != DRAFT:
        return u"An approved study is not changed."
    if not (reason or u"").strip():
        return u"Say why the result is excluded."
    rec.setdefault("exclusions", []).append({"injection": injection, "analyte": analyte or u"*",
                                             "reason": reason.strip(), "by": by, "at": at})
    return u""


def approve(records, rec, results, applied, by, at, statement, file_name=u""):
    """Freeze the study and supersede the earlier approved one of its kind."""
    if rec.get("status") != DRAFT:
        return u"Already approved."
    if not (statement or u"").strip():
        return u"Approval needs a statement."
    if not results:
        return u"Nothing to approve: the study has no results."
    for other in records:
        if (other is not rec and other.get("status") == APPROVED and other.get("kind") == rec["kind"]
                and other.get("method") == rec["method"] and other.get("matrix") == rec["matrix"]):
            other["status"] = SUPERSEDED
            other["superseded_by"] = rec["id"]
    rec.update(status=APPROVED, results=results, applied=applied, approved_by=by,
               approved_at=at, statement=statement.strip(), file=file_name)
    return u""


def apply_to_profile(profile, matrix, applied):
    """A copy of the profile's Reporting Limits with the study's values
    written in (only the fields the study sets)."""
    import copy
    p = copy.deepcopy(profile or {})
    rls = p.setdefault("reporting_limits", {}).setdefault(matrix, {})
    for kw, vals in (applied or {}).items():
        rls.setdefault(kw, {}).update(vals)
    return p


# ── storage ──────────────────────────────────────────────────────────────────

def load(portal):
    from zope.annotation.interfaces import IAnnotations
    try:
        return [normalise(r) for r in json.loads(IAnnotations(portal).get(KEY) or u"[]")]
    except (TypeError, ValueError):
        return []


def save(portal, records):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(portal)[KEY] = json.dumps(records)


def find(records, sid):
    for r in records:
        if r.get("id") == sid:
            return r
    return None
