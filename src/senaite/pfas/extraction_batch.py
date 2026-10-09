# -*- coding: utf-8 -*-
"""The extraction batch and its members.

The extraction batch is the WORKSHEET: its samples are the samples of
its analyses (core's Add Analyses is how they are selected), and its QC
members are records on it, populated from the method profile's QC
composition or the project plan, each QC given its parent before labels are
issued. Every member carries the injection name the LIMS issues: a
sample's SENAITE id, a QC "<worksheet>-<role><n>".

    member = {"id", "role", "sample_uid", "sample_id", "client_sid", "matrix",
              "parent" (a sample member's id), "lfsm_of" (an LFSMD: its LFSM
              member's id), "level", "amount", "unit", "injection",
              "lot" (an MxB: the blank-matrix reagent lot's uid, whose
              assigned levels it is shown against; matrix_blank.py),
              "added_by", "added_at"}

Pure (Python 2.7 and 3):

    plan_qc(profile, comp, n_samples)       -> {role: count}
    sync_samples(members, samples)          -> members with the samples' rows
    populate(members, plan, ws_id, by, at)  -> members with the QC shortfall
    problems(members, limit=None)           -> ["what is wrong", ...]
    batch_size(members, limit)              -> (counted, max) or None
    spike_map(members)                      -> {injection: {...}} for the worker

Plone (the worksheet annotation):

    mark_subtraction_blank(members, member_id) -> "" | why not
    subtraction_blank(members)              -> the marked method blank
    load(ws) / save(ws, members)
"""
from __future__ import absolute_import, unicode_literals

import json
import math

KEY = "senaite.pfas.extraction_members"

# batch order: blanks, fortified blanks, then the sample-linked QC
QC_ROLES = (u"MB", u"LRB", u"MxB", u"LFB", u"LCS", u"LFSM", u"LFSMD", u"Dup")
NEEDS_PARENT = frozenset((u"LFSM", u"LFSMD", u"Dup", u"MxB"))
SPIKED = frozenset((u"LFSM", u"LFSMD", u"LFB", u"LCS"))
ROLE_TITLES = {u"MB": u"Method blank", u"LRB": u"Laboratory reagent blank",
               u"MxB": u"Matrix blank", u"LFB": u"Laboratory fortified blank",
               u"LCS": u"Laboratory control sample", u"LFSM": u"Matrix spike (LFSM)",
               u"LFSMD": u"Matrix spike duplicate (LFSMD)", u"Dup": u"Sample duplicate"}


def _int(v):
    try:
        return int(v) if v not in (None, u"", "") else None
    except (TypeError, ValueError):
        return None


def plan_qc(profile, comp, n_samples):
    """{role: count} the batch needs. The method's QC types that are switched
    on, each `per_batch` (blank: 1; the sample duplicate 0, as it stands in
    for the LFSMD); `LFSM.frequency` N adds LFSMs to one per N samples; the
    project plan's `comp` (same keys) overrides the method's."""
    qca = (profile or {}).get("qc_acceptance") or {}
    comp = comp or {}
    out = {}
    for role in QC_ROLES:
        conf = dict(qca.get(role) or {})
        conf.update(comp.get(role) or {})
        if not (qca.get(role) or {}).get("enabled"):
            continue
        count = _int(conf.get("per_batch"))
        if count is None:
            count = 0 if role == u"Dup" else 1
        if role == u"LFSM":
            every = _int(conf.get("frequency"))
            if every:
                count = max(count, int(math.ceil(float(n_samples) / every)) if n_samples else 0)
        if role == u"Dup" and (conf.get("duplicate_all_samples") or u"") == u"yes":
            count = max(count, n_samples)
        if count:
            out[role] = count
    return out


def _next_id(members):
    n = 0
    for m in members:
        try:
            n = max(n, int((m.get("id") or u"m0")[1:]))
        except ValueError:
            pass
    return u"m%d" % (n + 1)


def sync_samples(members, samples):
    """Members with one row per sample of the worksheet (`samples` =
    [{"uid", "id", "client_sid", "matrix"}]): new samples added, samples
    that left the worksheet removed (with any parent link to them cleared)."""
    members = [dict(m) for m in members or []]
    by_uid = dict((s["uid"], s) for s in samples or [])
    gone = set(m["id"] for m in members if m.get("role") == u"Sample" and m.get("sample_uid") not in by_uid)
    out = []
    for m in members:
        if m["id"] in gone:
            continue
        if m.get("parent") in gone:
            m["parent"] = u""
        out.append(m)
    have = set(m.get("sample_uid") for m in out if m.get("role") == u"Sample")
    for s in samples or []:
        if s["uid"] in have:
            continue
        out.append({"id": _next_id(out), "role": u"Sample", "sample_uid": s["uid"],
                    "sample_id": s["id"], "client_sid": s.get("client_sid") or u"",
                    "matrix": s.get("matrix") or u"", "parent": u"", "lfsm_of": u"",
                    "level": u"", "amount": u"", "unit": u"", "injection": s["id"]})
    return out


def _injection(ws_id, role, members):
    used = set(m.get("injection") for m in members)
    n = 1
    while u"%s-%s%d" % (ws_id, role, n) in used:
        n += 1
    return u"%s-%s%d" % (ws_id, role, n)


def populate(members, plan, ws_id, by=u"", at=u""):
    """Add the QC the plan asks for that the batch does not hold yet (never
    removes one). Parents are suggested in sample order -- the LFSMD takes
    its LFSM's -- and stay editable until labels are issued."""
    members = [dict(m) for m in members or []]
    samples = [m for m in members if m.get("role") == u"Sample"]
    for role in QC_ROLES:
        want = plan.get(role) or 0
        held = [m for m in members if m.get("role") == role]
        for i in range(len(held), want):
            m = {"id": _next_id(members), "role": role, "sample_uid": u"", "sample_id": u"",
                 "client_sid": u"", "matrix": u"", "parent": u"", "lfsm_of": u"",
                 "level": u"", "amount": u"", "unit": u"", "lot": u"",
                 "injection": _injection(ws_id, role, members), "added_by": by, "added_at": at}
            if role in (u"LFSM", u"Dup", u"MxB") and samples:
                m["parent"] = samples[i % len(samples)]["id"]
            if role == u"LFSMD":
                lfsms = [x for x in members if x.get("role") == u"LFSM"]
                taken = set(x.get("lfsm_of") for x in members if x.get("role") == u"LFSMD")
                free = [x for x in lfsms if x["id"] not in taken]
                if free:
                    m["lfsm_of"] = free[0]["id"]
                    m["parent"], m["level"] = free[0].get("parent") or u"", free[0].get("level") or u""
            members.append(m)
    return default_subtraction_blank(members)


def default_subtraction_blank(members):
    """The first method blank is the subtraction blank until someone chooses
    another ("batch default, reviewer can change")."""
    mbs = [m for m in members if m.get("role") == u"MB"]
    if mbs and not any(m.get("subtract") for m in mbs):
        mbs[0]["subtract"] = True
    return members


def mark_subtraction_blank(members, member_id):
    """Make one method blank the subtraction blank; '' when it is one, else
    why not."""
    target = [m for m in members if m.get("id") == member_id]
    if not target or target[0].get("role") != u"MB":
        return u"Choose one of the batch's method blanks."
    for m in members:
        if m.get("role") == u"MB":
            m["subtract"] = m is target[0]
    return u""


def subtraction_blank(members):
    """The marked method blank's member, or None."""
    return next((m for m in members if m.get("role") == u"MB" and m.get("subtract")), None)


def follow_lfsm(members):
    """Every LFSMD takes its LFSM's parent, level, amount and unit: they cannot
    differ."""
    by_id = dict((m["id"], m) for m in members)
    for m in members:
        if m.get("role") == u"LFSMD" and m.get("lfsm_of") in by_id:
            lfsm = by_id[m["lfsm_of"]]
            for k in ("parent", "level", "amount", "unit"):
                m[k] = lfsm.get(k) or u""
    return members


def batch_size(members, limit):
    """(members counted, the method's maximum) or None when the method sets
    no maximum. `limit` is the method profile's extraction_batch section:
    max_size, and count_qc (QC members count towards it; otherwise samples
    only). "X samples total including QC or excluding qc"."""
    limit = limit or {}
    try:
        top = int(limit.get("max_size") or 0)
    except (TypeError, ValueError):
        return None
    if top < 1:
        return None
    counted = [m for m in members if limit.get("count_qc") or m.get("role") == u"Sample"]
    return len(counted), top


def problems(members, limit=None):
    """What stops the batch going to labels: more members than the method
    allows, a QC without its parent, a parent that is not one of the batch's
    samples, an LFSMD without its LFSM, a spike without a level, an amount
    without a unit, a name used twice."""
    out = []
    size = batch_size(members, limit)
    if size and size[0] > size[1]:
        out.append(u"The batch holds %d %s; the method allows %d. Move %d to another batch."
                   % (size[0], u"members" if (limit or {}).get("count_qc") else u"samples",
                      size[1], size[0] - size[1]))
    by_id = dict((m["id"], m) for m in members)
    names = {}
    for m in members:
        role, label = m.get("role"), m.get("injection") or m.get("id")
        names.setdefault(m.get("injection"), []).append(label)
        if role in NEEDS_PARENT:
            parent = by_id.get(m.get("parent"))
            if parent is None or parent.get("role") != u"Sample":
                out.append(u"%s: choose the sample it is made from." % label)
        if role == u"LFSMD":
            lfsm = by_id.get(m.get("lfsm_of"))
            if lfsm is None or lfsm.get("role") != u"LFSM":
                out.append(u"%s: choose the LFSM it duplicates." % label)
        if role == u"MxB" and not (m.get("lot") or u"").strip():
            out.append(u"%s: choose the blank-matrix lot it is made from." % label)
        if role in SPIKED and not (m.get("level") or u"").strip() and not (
                role == u"LFSMD" and m.get("lfsm_of") in by_id):   # it follows its LFSM
            out.append(u"%s: choose the spike level." % label)
        if (m.get("amount") or u"") != u"" and not (m.get("unit") or u"").strip():
            out.append(u"%s: an amount needs the matrix's reporting unit." % label)
    for name, who in names.items():
        if name and len(who) > 1:
            out.append(u"%s is used by %d members." % (name, len(who)))
    return out


def spike_map(members):
    """The worker's spike / duplicate record, from the members (the only
    source: no parent or level is read from a name)."""
    by_id = dict((m["id"], m) for m in members)
    out = {}
    for m in members:
        role = m.get("role")
        if role not in SPIKED and role not in (u"Dup", u"MxB"):
            continue
        parent = by_id.get(m.get("parent")) or {}
        lfsm = by_id.get(m.get("lfsm_of")) or {}
        try:
            amount = float(m.get("amount")) if (m.get("amount") or u"") != u"" else None
        except (TypeError, ValueError):
            amount = None
        out[m.get("injection")] = {
            "parent": parent.get("injection") or u"", "qc_type": role,
            "level": m.get("level") or u"", "spike": amount,
            "spike_unit": (m.get("unit") or u"") if amount is not None else u"",
            "lfsm": lfsm.get("injection") or u""}
    return out


def rekey_rows(rows, members):
    """Extraction Log rows written before the batch had members name a sample
    by its Client Sample ID; its member's LIMS-issued injection name is the
    key now. A dilution's parent is renamed the same way."""
    names = dict((m.get("client_sid"), m.get("injection")) for m in members or []
                 if m.get("role") == u"Sample" and m.get("client_sid") and m.get("injection"))
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        r = dict(r)
        if r.get("sample_id") in names:
            r["sample_id"] = names[r["sample_id"]]
        if r.get("dilution_of") in names:
            r["dilution_of"] = names[r["dilution_of"]]
        out.append(r)
    return out


# ── dilution / re-injection requests ───────────────────────────────────
# The reviewer asks; the bench makes it and the LIMS names it; the next run
# carries it ("a place to log this and communicate this to
# the bench chemist"). Statuses: open -> made -> run (or cancelled).

REQUESTS_KEY = "senaite.pfas.run_requests"
REQUEST_KINDS = (u"dilution", u"reinjection")


def new_request(requests, members, injection, kind, fold, reason, by, at):
    """(requests, error): one more request, refused without a member to act
    on, a reason, or (a dilution) a fold above 1."""
    requests = [dict(r) for r in requests or []]
    names = set(m.get("injection") for m in members or [])
    if kind not in REQUEST_KINDS:
        return requests, u"Ask for a dilution or a re-injection."
    if injection not in names:
        return requests, u"Choose one of the batch's injections."
    if not (reason or u"").strip():
        return requests, u"Say why."
    fold_v = None
    if kind == u"dilution":
        try:
            fold_v = float(fold)
        except (TypeError, ValueError):
            fold_v = None
        if not fold_v or fold_v <= 1:
            return requests, u"Give the dilution's fold, a number above 1."
    if any(r.get("injection") == injection and r.get("kind") == kind and r.get("status") in (u"open", u"made")
           for r in requests):
        return requests, u"%s already has an open %s request." % (injection, kind)
    requests.append({"id": u"r%d" % (len(requests) + 1), "kind": kind, "injection": injection,
                     "fold": (u"%g" % fold_v) if fold_v else u"", "reason": reason.strip(),
                     "requested_by": by, "requested_at": at, "status": u"open",
                     "made_by": u"", "made_at": u"", "new_injection": u""})
    return requests, u""


def made_name(request, requests):
    """The LIMS-issued name of what the bench makes: '<injection>-D<fold>' for
    a dilution, '<injection>-RI<n>' for a re-injection."""
    base = request["injection"]
    if request["kind"] == u"dilution":
        return u"%s-D%s" % (base, request["fold"])
    n = len([r for r in requests if r.get("kind") == u"reinjection" and r.get("injection") == base
             and r.get("new_injection")]) + 1
    return u"%s-RI%d" % (base, n)


def mark_made(requests, rid, by, at):
    """(requests, request, error): the request made, its injection named."""
    requests = [dict(r) for r in requests or []]
    req = next((r for r in requests if r.get("id") == rid), None)
    if req is None or req.get("status") != u"open":
        return requests, None, u"No open request %s." % rid
    req.update(status=u"made", made_by=by, made_at=at, new_injection=made_name(req, requests))
    return requests, req, u""


def reinjection_aliases(requests, members):
    """{new injection: {"role", "sample_uid", "replaces"}} for re-injections
    made: the worker files them as their original and drops the original."""
    by_name = dict((m.get("injection"), m) for m in members or [])
    out = {}
    for r in requests or []:
        if r.get("kind") == u"reinjection" and r.get("new_injection") and r.get("status") in (u"made", u"run"):
            m = by_name.get(r["injection"]) or {}
            out[r["new_injection"]] = {"role": m.get("role") or u"Sample",
                                       "sample_uid": m.get("sample_uid") or u"",
                                       # the re-injected blank stays the one
                                       # results use
                                       "subtract": bool(m.get("subtract")),
                                       "replaces": r["injection"]}
    return out


# ── labels ──────────────────────────────────────────────────────────────

LABELS_KEY = "senaite.pfas.extraction_labels"


def labels_signature(members):
    """What the labels print, per member: a change after they were issued
    means they are out of date."""
    by_id = dict((m["id"], m) for m in members)
    return sorted((m.get("injection") or u"", m.get("role") or u"",
                   (by_id.get(m.get("parent")) or {}).get("injection") or u"",
                   m.get("level") or u"") for m in members)


def label_rows(members, containers, meta):
    """One row per label: every member gets each container the method lists
    (`containers` = [{"container", "count", "for": all|samples}]), numbered
    "1 of 2" when there are several; with no list, one label per member.
    `meta`: worksheet, batch, method, date, analyst."""
    by_id = dict((m["id"], m) for m in members)
    containers = [c for c in containers or [] if (c.get("container") or u"").strip()] or \
        [{"container": u"", "count": 1, "for": u"all"}]
    out = []
    for m in members:
        for c in containers:
            if c.get("for") == u"samples" and m.get("role") != u"Sample":
                continue
            n = max(1, int(c.get("count") or 1))
            for i in range(n):
                name = c.get("container") or u""
                if n > 1:
                    name = u"%s %d of %d" % (name, i + 1, n)
                out.append(dict(meta, injection=m.get("injection") or u"", container=name.strip(),
                                role=ROLE_TITLES.get(m.get("role"), m.get("role")) if m.get("role") != u"Sample" else u"",
                                sample_id=m.get("sample_id") or u"", client_sid=m.get("client_sid") or u"",
                                parent=(by_id.get(m.get("parent")) or {}).get("injection") or u"",
                                level=m.get("level") or u"", matrix=m.get("matrix") or meta.get("matrix") or u""))
    return out


# ── the worksheet annotation ──────────────────────────────────────────────────

def load(ws):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(ws).get(KEY) or u"[]")
    except (ValueError, TypeError):
        return []


def save(ws, members):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(ws)[KEY] = json.dumps(members)


def load_requests(ws):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(ws).get(REQUESTS_KEY) or u"[]")
    except (ValueError, TypeError):
        return []


def save_requests(ws, requests):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(ws)[REQUESTS_KEY] = json.dumps(requests)


def label_issues(ws):
    """[{at, by, labels, signature, reason}] -- every issue of the labels."""
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(ws).get(LABELS_KEY) or u"[]")
    except (ValueError, TypeError):
        return []


def record_label_issue(ws, entry):
    from zope.annotation.interfaces import IAnnotations
    issues = label_issues(ws) + [entry]
    IAnnotations(ws)[LABELS_KEY] = json.dumps(issues)
    return issues


def worksheet_samples(ws):
    """[{"uid", "id", "client_sid", "matrix"}] for the samples of the
    worksheet's analyses (core's Add Analyses selects them)."""
    from senaite.pfas.core_fields import samples_of
    out = []
    for s in samples_of(ws):
        st = s.getSampleType() if hasattr(s, "getSampleType") else None
        out.append({"uid": s.UID(), "id": s.getId(), "client_sid": s.getClientSampleID() or u"",
                    "matrix": st.Title() if st is not None else u""})
    return sorted(out, key=lambda r: r["id"])


def is_worksheet(obj):
    return getattr(obj, "portal_type", "") == "Worksheet"


def worksheets_of(batch):
    """The worksheets holding the batch's analyses."""
    seen, out = set(), []
    try:
        for sample in batch.getAnalysisRequests() or []:
            for an in sample.getAnalyses(full_objects=True):
                ws = an.getWorksheet() if hasattr(an, "getWorksheet") else None
                if ws is not None and ws.UID() not in seen:
                    seen.add(ws.UID())
                    out.append(ws)
    except Exception:                                       # noqa: BLE001
        pass
    return out


def home(obj):
    """Where the extraction record lives: the worksheet. Given a client
    Batch (an older link), its one worksheet; the Batch itself only while it
    has no worksheet or several (an older record not yet moved)."""
    if obj is None or is_worksheet(obj):
        return obj
    wss = worksheets_of(obj)
    return wss[0] if len(wss) == 1 else obj


def linked_batch(ws):
    """The client Batch most of the worksheet's samples belong to, or None."""
    from senaite.pfas.core_fields import samples_of
    counts = {}
    for s in samples_of(ws) if is_worksheet(ws) else []:
        b = s.getBatch() if hasattr(s, "getBatch") else None
        if b is not None:
            counts[b.UID()] = (counts.get(b.UID(), (0, b))[0] + 1, b)
    if not counts:
        return None
    return sorted(counts.values(), key=lambda c: -c[0])[0][1]
