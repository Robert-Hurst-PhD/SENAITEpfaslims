# -*- coding: utf-8 -*-
"""The extraction batch and its members.

The extraction batch is the WORKSHEET: its samples are the samples of
its analyses (core's Add Analyses is how they are selected), and its QC
members are records on it, populated from the method profile's QC
composition or the project plan, each QC given its parent before labels are
issued. Every member carries the injection name the LIMS issues: until the
batch's first labels, a sample's SENAITE id and a QC "<worksheet>-<role><n>";
at that first issue the batch takes its number for the day and each member
its name by the scheme (injection_names.py, name_members). A batch whose
labels were issued before keeps its names.

    member = {"id", "role", "sample_uid", "sample_id", "client_sid", "matrix",
              "parent" (a sample member's id), "lfsm_of" (an LFSMD: its LFSM
              member's id), "level", "amount", "unit", "injection",
              "lot" (an MxB: the blank-matrix reagent lot's uid, whose
              assigned levels it is shown against; matrix_blank.py),
              "spike_lot", "spike_volume_ul" (a spiked member: the lot
              number of the spike it was made with, chosen from the
              inventory, and the volume added in uL; only a member created
              with them records them, see records_spike; an LFSMD follows
              its LFSM's, see spike_of),
              "added_by", "added_at"}

Pure (Python 2.7 and 3):

    plan_qc(profile, comp, n_samples)       -> {role: count}
    sync_samples(members, samples)          -> members with the samples' rows
    populate(members, plan, ws_id, by, at)  -> members with the QC shortfall
    problems(members, limit=None)           -> ["what is wrong", ...]
    batch_size(members, limit)              -> (counted, max) or None
    spike_map(members)                      -> {injection: {...}} for the worker
    sample_injections(members, sample_uid)  -> the names issued for one sample
    records_spike(member)                   -> whether it records its spike lot
    spike_of(member, members)               -> (lot, volume uL): its own, an LFSMD's its LFSM's
    set_spikes(members, {id: (lot, uL)})    -> members with their spike lots
    spike_volume_problem(text)              -> "" | why the volume is refused

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
# what a spiked member records of its spike: the lot number and the volume
# added (uL). The members are part of the extraction hash, so a member
# created without them never takes them: its record hashes as signed.
SPIKE_KEYS = ("spike_lot", "spike_volume_ul")
# the LFSMD is its LFSM's duplicate: it follows its LFSM's spike lot and
# volume (spike_of), and records none of its own. One created before that
# keeps the keys it was created with, so its record hashes as signed.
FOLLOWS_LFSM = u"LFSMD"
RECORDS_OWN_SPIKE = SPIKED - frozenset((FOLLOWS_LFSM,))
ROLE_TITLES = {u"MB": u"Method blank", u"LRB": u"Laboratory reagent blank",
               u"MxB": u"Matrix blank", u"LFB": u"Laboratory fortified blank",
               u"LCS": u"Laboratory control sample", u"LFSM": u"Matrix spike (LFSM)",
               u"LFSMD": u"Matrix spike duplicate (LFSMD)", u"Dup": u"Sample duplicate"}


def _int(v):
    try:
        return int(v) if v not in (None, u"", "") else None
    except (TypeError, ValueError):
        return None


def blank_count(profile, role):
    """How many of `role` a batch gets while its `per_batch` is blank: none
    for a QC type the method does not switch on, none for the sample
    duplicate (it stands in for the LFSMD), else one. The method profile
    shows this number in an empty per-batch box."""
    if not (((profile or {}).get("qc_acceptance") or {}).get(role) or {}).get("enabled"):
        return 0
    return 0 if role == u"Dup" else 1


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
            count = blank_count(profile, role)
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


def name_members(members, method_code, matrix_code, batch):
    """Members named by the scheme (injection_names.py), for an extraction
    batch numbered `batch` (261006-01). A member already named by it keeps its
    name; the rest are named and marked. `matrix_code(matrix)` gives a
    matrix's code. Names stay unique in the batch."""
    from senaite.pfas import injection_names as nm
    members = [dict(m) for m in members or []]
    by_id = dict((m["id"], m) for m in members)
    samples = [m for m in members if m.get("role") == u"Sample"]
    mats = [s.get("matrix") for s in samples if s.get("matrix")]
    main = max(set(mats), key=mats.count) if mats else u""
    used = set(m.get("injection") for m in members if m.get("named"))
    for m in members:
        if m.get("named"):
            continue
        role = m.get("role") or u""
        parent = by_id.get(m.get("parent")) or {}
        if role == u"Sample":
            name = nm.extracted(method_code, matrix_code(m.get("matrix") or main),
                                m.get("sample_id") or m.get("injection"), batch)
        elif parent:
            name = nm.extracted(method_code, matrix_code(parent.get("matrix") or main),
                                parent.get("sample_id") or parent.get("injection"), batch,
                                qc=nm.role_part(role, m.get("level")))
        else:
            name = nm.extracted(method_code, matrix_code(main), nm.role_part(role, m.get("level")), batch)
        base, n = name, 1
        while name in used:
            n += 1
            name = u"%s_%02d" % (base, n)
        used.add(name)
        m["injection"], m["named"] = name, True
    return members


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
            if role in RECORDS_OWN_SPIKE:
                m.update(dict((k, u"") for k in SPIKE_KEYS))
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


def records_spike(member):
    """True for a spiked member created with its spike keys (SPIKE_KEYS):
    only such a member records its spike lot and volume. An LFSMD never
    does: it follows its LFSM's (spike_of)."""
    member = member or {}
    return member.get("role") in RECORDS_OWN_SPIKE and all(k in member for k in SPIKE_KEYS)


def _given(value):
    return (u"%s" % (value if value is not None else u"")).strip() != u""


def spike_of(member, members):
    """(lot number, volume in uL) a spiked member was made with, u"" where
    none is recorded. An LFSMD follows its LFSM (lfsm_of): the lot and
    volume its LFSM recorded; one that recorded its own before it followed
    keeps what it recorded, so an older record reads as it was."""
    member = member or {}
    own = tuple((u"%s" % (member.get(k) or u"")).strip() for k in SPIKE_KEYS)
    if member.get("role") != FOLLOWS_LFSM or any(_given(v) for v in own):
        return own
    lfsm = [m for m in members or [] if m.get("id") == member.get("lfsm_of")
            and m.get("role") == u"LFSM"]
    if not lfsm:
        return own
    return tuple((u"%s" % (lfsm[0].get(k) or u"")).strip() for k in SPIKE_KEYS)


def set_spikes(members, values):
    """Members with each spike's lot and volume from `values` = {member id:
    (lot number, volume in uL)}, written only onto members that record them
    (records_spike); every other member is left exactly as it is."""
    members = [dict(m) for m in members or []]
    for m in members:
        if m.get("id") in (values or {}) and records_spike(m):
            lot, volume = values[m["id"]]
            m["spike_lot"] = (lot or u"").strip()
            m["spike_volume_ul"] = (volume or u"").strip()
    return members


def spike_volume_problem(text):
    """"" when `text` is blank or a volume greater than 0 (uL), else why not."""
    text = (text or u"").strip()
    if not text:
        return u""
    try:
        ok = float(text) > 0
    except (TypeError, ValueError):
        ok = False
    return u"" if ok else u"A spike volume is a number of \u00b5L greater than 0."


def lfsmd_spike_cells(member, members):
    """An LFSMD's spike lot and volume cells, [lot, volume]: its LFSM's, each
    said to be its LFSM's; one that recorded its own before it followed
    shows its own. None for any other member."""
    if (member or {}).get("role") != FOLLOWS_LFSM:
        return None
    lot, volume = spike_of(member, members)
    if any(_given(member.get(k)) for k in SPIKE_KEYS):
        return [lot or u"Not recorded", volume or u"Not recorded"]
    return [u"Its LFSM: %s" % (v or u"not recorded") for v in (lot, volume)]


# What a member records at the bench, posted as "<member id>.<fact>" by the
# extraction batch page: read only once the extraction is finalised (the
# finaliser signed over them); the subtraction blank is a review choice and
# stays open.
MEMBER_FACTS = ("parent", "lfsm_of", "level", "lot", "amount", "spike_lot", "spike_volume_ul")
# the page's actions that add, remove or populate members
MEMBER_ACTIONS = ("populate", "add", "remove")
FINALISED_REFUSED = u"The extraction is finalised: its members are read only. Nothing was saved."


def finalised_refusal(action, members, form, finalised):
    """Why a POST to the extraction batch page is refused because the
    extraction is finalised, or "": once finalised, no member is added,
    removed or populated, and a save that posts any member fact other than
    the one stored is refused whole. A fact posted as stored is no change;
    marking a request made and issuing labels are judged elsewhere."""
    if not finalised:
        return u""
    if action in MEMBER_ACTIONS:
        return FINALISED_REFUSED
    if action == u"save":
        form = form or {}
        for m in members or ():
            for fact in MEMBER_FACTS:
                key = u"%s.%s" % (m.get("id"), fact)
                if key in form and _fact(form.get(key)) != _fact(m.get(fact)):
                    return FINALISED_REFUSED
    return u""


def _fact(value):
    return (u"%s" % (value if value is not None else u"")).strip()


def renamed(before, after):
    """True when `after` gives any member another injection name than
    `before` does (a name issued once, never changed after Finalise)."""
    names = dict((m.get("id"), m.get("injection")) for m in before or ())
    return any(names.get(m.get("id")) != m.get("injection") for m in after or ())


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
        return u"Choose one of the worksheet's method blanks."
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
    only), with `state`, its Worksheet size box's state (limit_states):
    Off sets no maximum. "X samples total including QC or excluding qc"."""
    limit = limit or {}
    if limit.get("state") == "off":
        return None
    try:
        top = int(limit.get("max_size") or 0)
    except (TypeError, ValueError):
        return None
    if top < 1:
        return None
    counted = [m for m in members if limit.get("count_qc") or m.get("role") == u"Sample"]
    return len(counted), top


def over_size_words(size, limit):
    return (u"The worksheet holds %d %s; the method allows %d. Move %d to another worksheet."
            % (size[0], u"members" if (limit or {}).get("count_qc") else u"samples",
               size[1], size[0] - size[1]))


def size_advisory(members, limit=None):
    """The worksheet over its maximum while the Worksheet size box is in the
    state Evaluate: what is said, holding nothing; else u''."""
    size = batch_size(members, limit)
    if size and size[0] > size[1] and (limit or {}).get("state") == "evaluate":
        return over_size_words(size, limit)
    return u""


def problems(members, limit=None):
    """What stops the batch going to labels: more members than the method
    allows, a QC without its parent, a parent that is not one of the batch's
    samples, an LFSMD without its LFSM, a spike without a level, an amount
    without a unit, a name used twice."""
    out = []
    size = batch_size(members, limit)
    state = (limit or {}).get("state") or "enforced"
    # the Worksheet size box: Enforced holds the worksheet over its maximum,
    # and one with no maximum set; Evaluate says so without holding it
    # (size_advisory); Off is not judged
    if size and size[0] > size[1] and state == "enforced":
        out.append(over_size_words(size, limit))
    elif state == "enforced" and "state" in (limit or {}) and size is None:
        out.append(u"The method's Worksheet size is Enforced with no limit set. Set the most per "
                   u"worksheet on its Run & reporting tab, or set the box Off.")
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
        return requests, u"Choose one of the worksheet's injections."
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


def planned_fold(pct=None, take=None, to=None):
    """A planned dilution's fold: from the share of the extract (a %, 10 % is
    10-fold) or from the volumes (taken, made up to). None when it is not a
    dilution (a fold of 1 or less, or nothing given)."""
    def num(v):
        try:
            return float(u"%s" % v)
        except (TypeError, ValueError):
            return None
    p, t, v = num(pct), num(take), num(to)
    fold = None
    if p:
        fold = 100.0 / p
    elif t and v:
        fold = v / t
    return round(fold, 6) if fold and fold > 1 else None


def add_planned(requests, members, plans, by, at):
    """(requests, errors): a dilution request per planned dilution,
    marked planned with its route. One run with this run ("with") is named now
    and marked in_run, so it is never offered again as a separate run; one run
    separately waits in Ready to build like any request."""
    from senaite.pfas.sample_table import route_key
    errors = []
    for p in plans or []:
        requests, err = new_request(requests, members, p.get("injection"), u"dilution", p.get("fold"),
                                    u"Planned dilution", by, at)
        if err:
            errors.append(u"%s: %s" % (p.get("injection"), err))
            continue
        req = requests[-1]
        route = route_key(p.get("route"))
        # a re-prepared smaller aliquot goes to the next extraction batch
        runs = u"separately" if route == u"reprep" else (p.get("runs") or u"separately")
        req.update(planned=True, route=route, runs=runs)
        if req["runs"] == u"with":
            req.update(in_run=True, new_injection=made_name(req, requests))
    return requests, errors


def made_name(request, requests):
    """The LIMS-issued name of what the bench makes: '<injection>-D<fold>' for
    a dilution, '<injection>-RI<n>' for a re-injection."""
    base = request["injection"]
    # a name by the scheme ends in its repeat part: _DIL10, _RE1 (injection_names.py)
    scheme = u"_" in base
    if request["kind"] == u"dilution":
        return (u"%s_DIL%s" if scheme else u"%s-D%s") % (base, request["fold"])
    n = len([r for r in requests if r.get("kind") == u"reinjection" and r.get("injection") == base
             and r.get("new_injection")]) + 1
    return (u"%s_RE%d" if scheme else u"%s-RI%d") % (base, n)


# how a labelled standard was handled when a dilution was made: the worker
# judges the injection IS against the topped-up
# level, or expects it at 1 / fold when not added; a surrogate not added is
# corrected by the fold, one added or topped up is read as measured
HANDLINGS = ((u"not_added", u"Not added"), (u"topped_up", u"Topped up"), (u"added", u"Added"))


from senaite.pfas.rounding import number as _num


def prep_from_form(form, rid):
    """A dilution's prep as the Make dialog posts it (fields <name>.<request id>)."""
    g = lambda k: (form.get(u"%s.%s" % (k, rid)) or u"").strip()     # noqa: E731
    return {"extract_ul": _num(g("extract_ul")), "final_ul": _num(g("final_ul")),
            "diluent_lot": g("diluent_lot"), "is_handling": g("is_handling"),
            "is_lot": g("is_lot"), "is_ul": _num(g("is_ul")),
            "sur_handling": g("sur_handling"), "sur_lot": g("sur_lot"), "sur_ul": _num(g("sur_ul"))}


def prep_problems(prep, fold):
    """What a dilution's prep lacks: volumes, the diluent, how each labelled
    standard was handled and, where added, its lot and volume. [] when complete."""
    out = []
    if not prep.get("extract_ul") or prep["extract_ul"] <= 0:
        out.append(u"Enter the extract taken (\u00b5L).")
    if not prep.get("final_ul") or prep["final_ul"] <= 0:
        out.append(u"Enter the final volume (\u00b5L).")
    if not prep.get("diluent_lot"):
        out.append(u"Choose the diluent lot.")
    for key, what in ((u"is", u"internal standard"), (u"sur", u"surrogate")):
        h = prep.get(u"%s_handling" % key)
        if h not in dict(HANDLINGS):
            out.append(u"Say how the %s was handled." % what)
        elif h != u"not_added" and (not prep.get(u"%s_lot" % key) or not prep.get(u"%s_ul" % key)):
            out.append(u"Choose the %s lot and its volume." % what)
    return out


def dilution_given(prep):
    """The dilution the volumes make (final / extract), or None."""
    if prep.get("extract_ul") and prep.get("final_ul"):
        return prep["final_ul"] / prep["extract_ul"]
    return None


def matches_fold(prep, fold):
    """The volumes give the fold asked for (within 1 %)."""
    given, f = dilution_given(prep), _num(fold)
    return bool(given and f) and abs(given - f) <= 0.01 * f


def mark_made(requests, rid, by, at, prep=None):
    """(requests, request, error): the request made, its injection named; a
    dilution keeps its prep (each dilution is its own vial)."""
    requests = [dict(r) for r in requests or []]
    req = next((r for r in requests if r.get("id") == rid), None)
    if req is None or req.get("status") != u"open":
        return requests, None, u"No open request %s." % rid
    req.update(status=u"made", made_by=by, made_at=at, new_injection=made_name(req, requests))
    if prep is not None:
        req["prep"] = dict(prep, given=dilution_given(prep), matches=matches_fold(prep, req.get("fold")))
    return requests, req, u""


def sample_injections(members, sample_uid):
    """The injection names the LIMS issued for one sample on a worksheet:
    its sample members' names, the names the worker binds its results by."""
    out = []
    for m in members or []:
        if m.get("role") == u"Sample" and sample_uid and m.get("sample_uid") == sample_uid:
            name = (m.get("injection") or u"").strip()
            if name and name not in out:
                out.append(name)
    return out


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

CODE_KEY = "senaite.pfas.extraction_batch_code"          # on the worksheet
CODES_KEY = "senaite.pfas.extraction_batch_codes"        # on the portal: every code issued


def batch_code_of(ws):
    """The worksheet's extraction batch number (261006-01), or "" when it was
    never given one (a batch named before the scheme keeps its names)."""
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(ws).get(CODE_KEY) or u""


def issue_batch_code(portal, ws, day_iso):
    """The day's next extraction batch number, given to the worksheet once."""
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import injection_names as nm
    have = batch_code_of(ws)
    if have:
        return have
    ann = IAnnotations(portal)
    codes = list(ann.get(CODES_KEY) or [])
    code = nm.batch_code(day_iso, nm.next_batch_number(day_iso, codes))
    ann[CODES_KEY] = codes + [code]
    IAnnotations(ws)[CODE_KEY] = code
    return code


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
    for sample in batch.getAnalysisRequests() or []:
        for an in sample.getAnalyses(full_objects=True):
            ws = an.getWorksheet() if hasattr(an, "getWorksheet") else None
            if ws is not None and ws.UID() not in seen:
                seen.add(ws.UID())
                out.append(ws)
    return out


def home(obj):
    """Where the extraction record lives: the worksheet. Given a client
    Batch (an older link), its one worksheet; the Batch itself only while it
    has no worksheet or several (an older record not yet moved). Anything
    else (the site, a page opened outside a batch) is its own home."""
    if getattr(obj, "portal_type", "") != "Batch":
        return obj
    wss = worksheets_of(obj)
    return wss[0] if len(wss) == 1 else obj


def samples_on(ws):
    """The worksheet's samples, found through the analysis catalog: only the
    samples are woken, never each analysis (a worksheet holds hundreds). In
    no set order; samples_of keeps the worksheet's own."""
    from bika.lims import api
    from senaite.pfas.core_fields import samples_of
    try:
        # the catalog itself: api.search with a portal_type finds nothing here
        brains = api.get_tool("senaite_catalog_analysis")(getWorksheetUID=api.get_uid(ws))
        # a byte-string path: traversal finds nothing by a unicode one
        paths = sorted(set(str(b.getPath().rsplit(str("/"), 1)[0]) for b in brains))
        # samples only: a duplicate analysis lives in the worksheet and a
        # reference analysis in its reference sample
        return [s for s in (api.get_object_by_path(p, None) for p in paths)
                if getattr(s, "portal_type", None) == "AnalysisRequest"]
    except Exception:                                       # noqa: BLE001
        return samples_of(ws)


def linked_batch(ws):
    """The client Batch most of the worksheet's samples belong to, or None."""
    counts = {}
    for s in samples_on(ws) if is_worksheet(ws) else []:
        b = s.getBatch() if hasattr(s, "getBatch") else None
        if b is not None:
            counts[b.UID()] = (counts.get(b.UID(), (0, b))[0] + 1, b)
    if not counts:
        return None
    return sorted(counts.values(), key=lambda c: -c[0])[0][1]


# ── the record in force ───────────────────────────────────────────────────
# A finalised extraction record is corrected only by entries in one log
# (extraction_amendments); the stored members and rows are never edited.
# What judges and files reads the record in force.

def amendments_state(ws):
    """The worksheet's extraction corrections (extraction_amendments.KEY),
    read without writing: a page or the worker's endpoint stores nothing."""
    from senaite.pfas import extraction_amendments as ea
    from zope.annotation.interfaces import IAnnotations
    return ea.load(IAnnotations(ws).get(ea.KEY))


def members_in_force(ws):
    """The worksheet's members with the amendments in force applied."""
    from senaite.pfas import extraction_amendments as ea
    return ea.members_in_force(load(ws), amendments_state(ws))


def samples_in_force(ws, rows):
    """The extraction table's sample rows (keyed as rekey_rows keys them)
    with the amendments in force applied."""
    from senaite.pfas import extraction_amendments as ea
    return ea.samples_in_force(rows, amendments_state(ws))


def relevelled(members, state):
    """The names in force of the members whose level an amendment in force
    changed (`members` as stored): their amount is the one the amendment
    gave, never an amount entered for the level as recorded."""
    from senaite.pfas import extraction_amendments as ea
    ids = set(mid for (mid, field) in ea.amendments_in_force(state, members) if field == ea.LEVEL)
    return set(m.get("injection") for m in ea.members_in_force(members, state) if m.get("id") in ids)


def by_alias(entries, members):
    """`entries` ({name: info}) with each issued name an amendment renamed
    (a member in force's "aliases") keyed to its name in force's info,
    marked "alias_of": a file acquired under the issued name still matches
    its member, as a re-injection matches its original. A name already
    keyed keeps its own entry."""
    entries = entries or {}
    out = dict(entries)
    for m in members or ():
        name = m.get("injection")
        if name not in entries:
            continue
        for old in m.get("aliases") or ():
            if old and old not in out:
                out[old] = dict(entries[name], alias_of=name)
    return out


def answering_members(members):
    """The members, and each again under every issued name an amendment
    renamed, for a lookup by the name on the vial (a re-injection request
    names it). A name another member answers to is not taken."""
    members = list(members or ())
    names = set(m.get("injection") for m in members)
    out = list(members)
    for m in members:
        for old in m.get("aliases") or ():
            if old and old not in names:
                names.add(old)
                out.append(dict(m, injection=old))
    return out


def _held(members):
    """{name, in force or issued: the re-extract entry id} for every member
    withheld for re-extraction."""
    out = {}
    for m in members or ():
        if not m.get("withheld"):
            continue
        for n in [m.get("injection")] + list(m.get("aliases") or ()):
            if n:
                out[n] = m["withheld"]
    return out


def withheld_names(members):
    """The names, in force and issued, of the members withheld for
    re-extraction (members in force)."""
    return sorted(_held(members))


def mark_withheld(entries, members):
    """`entries` with each withheld member's, and each re-injection of one
    ("replaces"), marked "withheld" (the re-extract entry id): the worker
    judges, files and pushes nothing of theirs."""
    held = _held(members)
    out = {}
    for k, v in (entries or {}).items():
        e = held.get(k) or held.get((v or {}).get("replaces"))
        out[k] = dict(v, withheld=e) if e else v
    return out
