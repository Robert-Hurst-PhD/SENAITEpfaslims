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
