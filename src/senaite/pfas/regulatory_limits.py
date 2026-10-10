# -*- coding: utf-8 -*-
"""Regulatory limits (MCLs, action levels) and program links for the
certificate's regulatory notes (part B).

A LIMIT is one record:
    id, program, label, analytes [keywords], matrices [sample type titles],
    value, unit, kind (MCL | Interim standard | Action level | Advisory),
    citation, effective, status_note, url, verified

`analytes` is a list because a limit may cover several reported analytes: a
sum-of-six state standard, or PFOS reported as linear + branched isomers. The
limit is compared with the SUM OF DETECTED values of its analytes (a
single-analyte limit is simply a list of one). Non-detects add nothing to the
sum -- stated on the certificate beside every such comparison.

A PROGRAM is who set the limit: "federal" (applies to every client) or a state
EDD profile id, which the client already selects for its
EDD (: program per client, with the EDD state).

NOTHING HERE IS A VERIFIED REGULATORY VALUE. The seeds were researched
2026-09-30 from the cited public pages and ship with verified=False; the
certificate uses ONLY limits the lab has marked verified (: never
fabricate a regulatory value). Federal status was changing at research time:
the May 2026 proposal to rescind the PFHxS, PFNA and HFPO-DA MCLs is recorded
on those records.

Evaluation is pure (no Zope) so the certificate and the tests share it.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import json
import re

STORE_KEY = "senaite.pfas.regulatory_limits"
# the shipped kinds; the lab's list is vocab_store "regulatory_limit_kinds"
try:
    from senaite.pfas.vocab_store import LISTS as _VOCAB  # noqa: E402
except ImportError:                                         # loaded by path (tests)
    from vocab_store import LISTS as _VOCAB  # noqa: E402
KINDS = tuple(k for k, _l in _VOCAB["regulatory_limit_kinds"][1])

# Units the comparison understands, as (dimension, factor to the base unit).
# Base units: ng/L for per-volume, ng/kg for per-mass. A limit and a result in
# different dimensions are never compared.
_UNITS = {
    "ng/l": ("vol", 1.0), "ug/l": ("vol", 1000.0), "µg/l": ("vol", 1000.0),
    "ng/ml": ("vol", 1000.0),
    "ng/kg": ("mass", 1.0), "ng/g": ("mass", 1000.0), "ug/kg": ("mass", 1000.0),
    "µg/kg": ("mass", 1000.0), "ug/g": ("mass", 1e6),
}

FEDERAL = "federal"

_EPA_PAGE = "https://www.epa.gov/sdwa/and-polyfluoroalkyl-substances-pfas"
_PFOS = ["PFOS", "br-PFOS"]
_PFHXS = ["PFHxS", "br-PFHxS"]
_RESCIND = ("EPA proposed rescinding this MCL in May 2026 (comment period closed "
            "2026-07-20); not final at research time.")

SEED_PROGRAMS = {
    FEDERAL: {"name": "US EPA", "links": [
        {"label": "EPA: PFAS National Primary Drinking Water Regulation", "url": _EPA_PAGE}]},
}


def _seed(id_, program, label, analytes, matrices, value, unit, kind, citation,
          effective, url, status_note=""):
    return {"id": id_, "program": program, "label": label, "analytes": analytes,
            "matrices": matrices, "value": value, "unit": unit, "kind": kind,
            "citation": citation, "effective": effective, "url": url,
            "status_note": status_note, "verified": False}


_NPDWR = "40 CFR Part 141, PFAS NPDWR (89 FR 32532, 2024-04-26)"
SEED_LIMITS = [
    _seed("fed-pfoa", FEDERAL, "PFOA", ["PFOA"], ["Drinking Water"], 4.0, "ng/L", "MCL",
          _NPDWR, "Compliance 2029 (extension to 2031 proposed May 2026)", _EPA_PAGE),
    _seed("fed-pfos", FEDERAL, "PFOS (linear + branched)", _PFOS, ["Drinking Water"], 4.0,
          "ng/L", "MCL", _NPDWR, "Compliance 2029 (extension to 2031 proposed May 2026)", _EPA_PAGE),
    _seed("fed-pfhxs", FEDERAL, "PFHxS (linear + branched)", _PFHXS, ["Drinking Water"], 10.0,
          "ng/L", "MCL", _NPDWR, "Compliance 2029", _EPA_PAGE, _RESCIND),
    _seed("fed-pfna", FEDERAL, "PFNA", ["PFNA"], ["Drinking Water"], 10.0, "ng/L", "MCL",
          _NPDWR, "Compliance 2029", _EPA_PAGE, _RESCIND),
    _seed("fed-hfpoda", FEDERAL, "HFPO-DA (GenX)", ["GenX"], ["Drinking Water"], 10.0,
          "ng/L", "MCL", _NPDWR, "Compliance 2029", _EPA_PAGE, _RESCIND),
]


# ── evaluation (pure) ────────────────────────────────────────────────────────

def convert(value, from_unit, to_unit):
    """value in from_unit expressed in to_unit, or None if not comparable."""
    a = _UNITS.get((from_unit or "").strip().lower())
    b = _UNITS.get((to_unit or "").strip().lower())
    if not a or not b or a[0] != b[0]:
        return None
    return value * a[1] / b[1]


def applicable(limits, programs, matrix):
    """Verified limits of the given programs that name this matrix."""
    progs = set(programs)
    m = (matrix or "").strip().lower()
    return [l for l in (limits or [])
            if l.get("verified") and l.get("program") in progs
            and m in [(x or "").strip().lower() for x in (l.get("matrices") or [])]]


def evaluate(limit, results, result_unit):
    """Compare one limit with a sample's results.

    results: {keyword: {"value": float or None (None = not detected),
                        "rl": float or None}}   all in result_unit.
    Returns None when none of the limit's analytes was reported, else
    {"status": "exceeds" | "below" | "undetermined" | "no_unit", "total",
     "limit_in_result_unit", "members", "detected"}.

    Rule: a detected sum at or above the limit exceeds.
    If the detected sum is below the limit but a non-detect's RL alone is at or
    above it, compliance cannot be determined. Without comparable units there is
    no comparison at all.
    """
    members = [k for k in (limit.get("analytes") or []) if k in results]
    if not members:
        return None
    lim = convert(float(limit["value"]), limit.get("unit"), result_unit)
    if lim is None:
        return {"status": "no_unit", "members": members, "detected": [],
                "total": None, "limit_in_result_unit": None}
    detected = [k for k in members if results[k].get("value") is not None]
    total = sum(results[k]["value"] for k in detected)
    if detected and total >= lim:
        status = "exceeds"
    elif any(results[k].get("value") is None and results[k].get("rl") is not None
             and results[k]["rl"] >= lim for k in members):
        status = "undetermined"
    elif any(results[k].get("value") is None and results[k].get("rl") is None
             for k in members):
        status = "undetermined"      # a non-detect with no RL says nothing
    else:
        status = "below"
    return {"status": status, "members": members, "detected": detected,
            "total": total if detected else None, "limit_in_result_unit": lim}


# ── the editor form (pure) ───────────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://[^\s\"'<>]+$")


def _split(text):
    return [x.strip() for x in (text or "").replace(";", ",").split(",") if x.strip()]


def parse_limits_form(form, old_limits, who, now):
    """Limit records from @@pfas-regulatory-limits' fields lim.<i>.<name>.

    Refuses (ValueError) a non-numeric or non-positive limit, an unknown unit,
    a record without label or analytes, and any link that is not http(s): a
    link prints on a client's certificate. Ticking Verified stamps who and when;
    the stamp is kept only while value, unit, analytes and matrices stay as
    they were verified."""
    old = dict((l.get("id"), l) for l in (old_limits or []))
    limits, i = [], 0
    while ("lim.%d.label" % i) in form:
        g = lambda k, _i=i: (u"%s" % (form.get("lim.%d.%s" % (_i, k)) or u"")).strip()   # noqa: E731
        i += 1
        if g("delete"):
            continue
        label, raw_value = g("label"), g("value")
        if not label and not raw_value:
            continue                                    # untouched blank row
        try:
            value = float(raw_value)
        except ValueError:
            raise ValueError(u"%s: the limit must be a number" % (label or u"new row"))
        if value <= 0:
            raise ValueError(u"%s: the limit must be above zero" % label)
        unit = g("unit")
        if convert(1.0, unit, unit) is None:
            raise ValueError(u"%s: unknown unit %r" % (label, unit))
        analytes = _split(g("analytes"))
        if not label or not analytes:
            raise ValueError(u"%s: a label and at least one analyte are required" % (label or u"new row"))
        url = g("url")
        if url and not _URL_RE.match(url):
            raise ValueError(u"%s: the link must be an http(s) address" % label)
        rid = g("id") or u"lim-%s-%d" % (now.replace(" ", "T"), i)
        rec = {"id": rid, "program": g("program") or FEDERAL, "label": label,
               "analytes": analytes, "matrices": _split(g("matrices")),
               "value": value, "unit": unit, "kind": g("kind") or KINDS[0],
               "citation": g("citation"), "effective": g("effective"),
               "status_note": g("status_note"), "url": url,
               "verified": bool(g("verified"))}
        prev = old.get(rid) or {}
        same = all(prev.get(k) == rec[k] for k in ("value", "unit", "analytes", "matrices"))
        if rec["verified"] and prev.get("verified") and same:
            rec["verified_by"] = prev.get("verified_by")
            rec["verified_at"] = prev.get("verified_at")
        elif rec["verified"]:
            rec["verified_by"] = who
            rec["verified_at"] = now
        limits.append(rec)
    return limits


def parse_programs_form(form, program_ids):
    programs = {}
    for pid in program_ids:
        links = []
        for line in (form.get("prog.%s.links" % pid) or u"").splitlines():
            if not line.strip():
                continue
            label, _, url = line.partition("|")
            url = url.strip()
            if not _URL_RE.match(url):
                raise ValueError(u"%s: %r is not an http(s) link (write: label | url)" % (pid, line.strip()))
            links.append({"label": label.strip() or url, "url": url})
        programs[pid] = {"name": (form.get("prog.%s.name" % pid) or pid).strip(), "links": links}
    return programs


# ── storage (Zope) ───────────────────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def get_store(portal):
    """{"programs": {...}, "limits": [...]} -- seeded on first read."""
    raw = _ann(portal).get(STORE_KEY)
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return {"programs": json.loads(json.dumps(SEED_PROGRAMS)),
            "limits": json.loads(json.dumps(SEED_LIMITS))}


def save_store(portal, data):
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(portal, 'regulatory_limits', "limits", lambda: get_store(portal), label=u"Regulatory limits")
    except Exception:
        pass
    _ann(portal)[STORE_KEY] = json.dumps(data, sort_keys=True)
