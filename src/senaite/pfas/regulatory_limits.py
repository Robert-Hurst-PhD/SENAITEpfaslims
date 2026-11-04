# -*- coding: utf-8 -*-
"""Regulatory limits (MCLs, action levels) and program links for the
certificate's regulatory notes (part B).

A LIMIT is one record:
    id, program, label, analytes [keywords], matrices [sample type titles],
    matrix_uids [the core Sample Types' UIDs], subtype_ids / subtypes [the
    sample sub-types it is narrowed to, if any], value, unit, kind (MCL |
    Interim standard | Action level | Advisory), citation, effective,
    status_note, url, verified, retired {by, at, why}

A limit's matrices are chosen from the core Sample Types and matched by UID
(titles are kept for display and older records); a limit with none is
refused, since it would never apply. A limit is RETIRED, never deleted: it
stops applying to new certificates and keeps its record, so a certificate
that used it still traces to it.

`analytes` is a list because a limit may cover several reported analytes: a
sum-of-six state standard, or PFOS reported as linear + branched isomers. The
limit is compared with the SUM OF DETECTED values of its analytes (a
single-analyte limit is simply a list of one). Non-detects add nothing to the
sum -- stated on the certificate beside every such comparison.

A PROGRAM is who set the limit: "federal" (applies to every client) or a state
EDD profile id, which the client already selects for its EDD: the program
follows the client's EDD state.

NOTHING HERE IS A VERIFIED REGULATORY VALUE. The seeds come from the cited
public pages and ship with verified=False; the certificate uses ONLY limits
the lab has marked verified (a regulatory value is never fabricated). The
May 2026 proposal to rescind the PFHxS, PFNA and HFPO-DA MCLs is recorded on
those records.

Evaluation is pure (no Zope) so the certificate and the tests share it.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import json
import re

STORE_KEY = "senaite.pfas.regulatory_limits"
# the shipped kinds; the lab's list is vocab_store "regulatory_limit_kinds"
from senaite.pfas.vocab_store import LISTS as _VOCAB  # noqa: E402
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


def analyte_column(analytes):
    """The analyte a limit is on, as the Regulatory Limits table shows it:
    the analyte only (PFOS, not the limit's name), the linear and branched
    forms one analyte, a sum's analytes joined by +."""
    out = []
    for a in analytes or []:
        a = (a or u"").strip()
        for pre in (u"lr-", u"br-"):
            if a.startswith(pre):
                a = a[len(pre):]
        if a and a not in out:
            out.append(a)
    return u" + ".join(out)

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


def is_active(limit):
    return not (limit or {}).get("retired")


def names_matrix(limit, matrix, matrix_uid=None):
    """The limit covers this matrix: by the Sample Type's UID when both
    carry one, else by title."""
    uids = limit.get("matrix_uids") or []
    if matrix_uid and uids:
        return matrix_uid in uids
    m = (matrix or "").strip().lower()
    return m in [(x or "").strip().lower() for x in (limit.get("matrices") or [])]


def applicable(limits, programs, matrix, matrix_uid=None, subtype=None):
    """Active, verified limits of the given programs that name this matrix.
    A limit naming sub-types applies only to a sample of one of them, and
    for that sample replaces the type-wide limit of the same program on the
    same analytes."""
    progs = set(programs)
    found = [l for l in (limits or [])
             if l.get("verified") and is_active(l) and l.get("program") in progs
             and names_matrix(l, matrix, matrix_uid)
             and (not l.get("subtype_ids") or subtype in l["subtype_ids"])]
    narrow = set((l.get("program"), tuple(sorted(l.get("analytes") or []))) for l in found if l.get("subtype_ids"))
    return [l for l in found
            if l.get("subtype_ids") or (l.get("program"), tuple(sorted(l.get("analytes") or []))) not in narrow]


def no_matrix(limit):
    return not (limit.get("matrix_uids") or limit.get("matrices"))


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


def _matrices(form, i, sample_types):
    """(titles, uids) ticked on row i (lim.<i>.mx.<uid>), in the Sample
    Types' order; without a Sample Type list, the typed titles."""
    if sample_types is None:
        return _split(form.get("lim.%d.matrices" % i)), []
    uids = [u for u, _t in sample_types if form.get("lim.%d.mx.%s" % (i, u))]
    titles = dict(sample_types)
    return [titles[u] for u in uids], uids


def _subtypes(form, i, subtypes, matrix_uids, label):
    """(ids, names) ticked on row i (lim.<i>.st.<id>); each must be a
    sub-type of a matrix the limit names."""
    ids, names = [], []
    for sid, name, type_uid in subtypes or []:
        if not form.get("lim.%d.st.%s" % (i, sid)):
            continue
        if type_uid not in (matrix_uids or []):
            raise ValueError(u"%s: %s is a sub-type of a matrix this limit does not name" % (label, name))
        ids.append(sid)
        names.append(name)
    return ids, names


def parse_limits_form(form, old_limits, who, now, sample_types=None, subtypes=None):
    """Limit records from @@pfas-regulatory-limits' fields lim.<i>.<name>.

    sample_types: [(uid, title)] the matrices are chosen from (checkboxes
    lim.<i>.mx.<uid>); subtypes: [(id, name, sample type uid)] a limit may
    narrow to (lim.<i>.st.<id>; sample_subtypes). Refuses (ValueError) a non-numeric or non-positive
    limit, an unknown unit, a record without label, analytes or a matrix,
    and any link that is not http(s): a link prints on a client's
    certificate. Ticking Verified stamps who and when; the stamp is kept
    only while value, unit, analytes and matrices stay as they were
    verified. A retired record keeps its retirement."""
    old = dict((l.get("id"), l) for l in (old_limits or []))
    limits, i = [], 0
    while ("lim.%d.label" % i) in form:
        g = lambda k, _i=i: (u"%s" % (form.get("lim.%d.%s" % (_i, k)) or u"")).strip()   # noqa: E731
        row = i
        i += 1
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
        matrices, matrix_uids = _matrices(form, row, sample_types)
        if not matrices:
            raise ValueError(u"%s: choose at least one matrix; a limit without one never applies" % label)
        url = g("url")
        if url and not _URL_RE.match(url):
            raise ValueError(u"%s: the link must be an http(s) address" % label)
        rid = g("id") or u"lim-%s-%d" % (now.replace(" ", "T"), i)
        rec = {"id": rid, "program": g("program") or FEDERAL, "label": label,
               "analytes": analytes, "matrices": matrices,
               "value": value, "unit": unit, "kind": g("kind") or KINDS[0],
               "citation": g("citation"), "effective": g("effective"),
               "status_note": g("status_note"), "url": url,
               "verified": bool(g("verified"))}
        if matrix_uids:
            rec["matrix_uids"] = matrix_uids
        st_ids, st_names = _subtypes(form, row, subtypes, matrix_uids, label)
        if st_ids:
            rec["subtype_ids"], rec["subtypes"] = st_ids, st_names
        prev = old.get(rid) or {}
        if prev.get("retired"):
            rec["retired"] = prev["retired"]
        same = all(prev.get(k) == rec[k] for k in ("value", "unit", "analytes", "matrices")) \
            and prev.get("subtype_ids") == rec.get("subtype_ids")
        if rec["verified"] and prev.get("verified") and same:
            rec["verified_by"] = prev.get("verified_by")
            rec["verified_at"] = prev.get("verified_at")
        elif rec["verified"]:
            rec["verified_by"] = who
            rec["verified_at"] = now
        limits.append(rec)
    return limits


def merge(old_limits, posted):
    """The stored list with the posted records put in place (by id); a new
    record goes at the end. Records not posted stay as they are."""
    by_id = dict((l.get("id"), l) for l in posted)
    out = [by_id.pop(l.get("id"), l) for l in (old_limits or [])]
    return out + [l for l in posted if l.get("id") in by_id]


def _find(limits, lid):
    for l in limits or []:
        if l.get("id") == lid:
            return l
    raise ValueError(u"There is no limit %r." % lid)


def retire(limits, lid, who, now, why):
    """Retire one limit (who, when, why); refused without a reason."""
    why = (why or u"").strip()
    if not why:
        raise ValueError(u"Say why the limit is retired.")
    lim = _find(limits, lid)
    if lim.get("retired"):
        raise ValueError(u"%s is already retired." % (lim.get("label") or lid))
    lim["retired"] = {"by": who, "at": now, "why": why}
    return limits


def mark_verified(limits, lid, who, now):
    """Stamp one limit verified; refused for a retired limit or one with no
    matrix (it would never apply)."""
    lim = _find(limits, lid)
    if lim.get("retired"):
        raise ValueError(u"%s is retired." % (lim.get("label") or lid))
    if no_matrix(lim):
        raise ValueError(u"%s: choose its matrices first (Update)." % (lim.get("label") or lid))
    lim.update({"verified": True, "verified_by": who, "verified_at": now})
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
    # the change history is strict: when its entry cannot be prepared the
    # save does not happen
    from senaite.pfas import config_history
    config_history.track(portal, 'regulatory_limits', "limits", lambda: get_store(portal), label=u"Regulatory limits")
    _ann(portal)[STORE_KEY] = json.dumps(data, sort_keys=True)
