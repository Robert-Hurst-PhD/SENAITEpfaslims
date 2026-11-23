# -*- coding: utf-8 -*-
"""Method studies: the data a study is calculated from, and the calculation
per analyte.

The worker stores every injection's result per analyte in the QC database
(injection_results, its run in batches). A study draws its replicates from
there:

  mdl  spiked samples (LFBs, or LFSMs spiked into blank matrix, at the
       study's spiking level) and method blanks of the method x matrix
       within the period (40 CFR 136 App. B Rev. 2 §4(b), §4(e): the last
       24 months); the spiked results are pooled as measured, with no
       blank or unspiked result subtracted (§2(d)(ii))
  mrl  seven LFBs at the proposed MRL, from the chosen worksheets (§9.2.6)
  pa   four to seven LFBs near mid-calibration (§9.2.3 / §9.2.4), their
       precision the RSD against the method profile's LFB RSD limit
  dl   seven or more LFBs near the DL over three days (§9.2.8.1)

A result is excluded only with a reason (App. B §2(b), §4(b): documented
gross failures). Python 2.7 and 3; the queries take a sqlite3 connection.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import method_studies as ms
from senaite.pfas import method_engine as me
from senaite.pfas import isomers
from senaite.pfas import compound_library as cl
from senaite.pfas.compound_library_store import library as _library


def keyword_for(name, library=None):
    """A native analyte's keyword from an export or published spelling."""
    return cl.native_keyword_for(library or _library(), name)

KINDS = [
    ("mdl", u"Annual MDL"),
    ("mrl", u"MRL confirmation"),
    ("pa", u"Precision and accuracy"),
    ("dl", u"Detection limit"),
    ("pt", u"Proficiency test"),
    ("idc", u"Initial demonstration of capability"),
]
# what a PT provider says of each reported analyte
PT_VERDICTS = [(u"acceptable", u"Acceptable"), (u"not_acceptable", u"Not acceptable")]
KIND_LABELS = dict(KINDS)
# kinds built on LFBs (reagent water fortified, EPA 537.1 §9.2): their
# spiked replicates are LFBs. Which methods run them is the method profile's
# study kinds (method_engine.study_kinds).
LFB_KINDS = ("mrl", "pa", "dl", "idc")
LFB = "LFB"


def kind_allowed(kind, profile):
    """True if the method (its profile) runs this kind of study."""
    return kind in me.study_kinds(profile)


# the QC types that are spiked: an MDL's spiked replicates are one of these
SPIKED_ROLES = ("LFB", "LFSM", "LFSMD")


def spike_role_choices(profile):
    """The spiked QC types the method runs (switched on), in SPIKED_ROLES
    order: an MDL's spiked-replicate choices. Blanks and duplicates are
    never spiked replicates."""
    types = (profile or {}).get("qc_acceptance") or {}
    return [c for c in SPIKED_ROLES if isinstance(types.get(c), dict) and types[c].get("enabled")]


# a study's preparations: the blanks and the spike levels, made replicates x
# days times each
PREPARATIONS = ((u"MB", u"Method blank"), (u"MxB", u"Matrix blank"), (u"Low", u"Low"), (u"Mid", u"Mid"),
                (u"High", u"High"))
BLANK_PREPARATIONS = (u"MB", u"MxB")


def design_table(preparations, replicates, days, concentrations):
    """([{"level", "concentration", "replicates", "days", "preparations"}], total)
    for the chosen preparations, in PREPARATIONS order; a blank has no
    concentration, a level the method's (else "not set")."""
    rows, total = [], 0
    for code, label in PREPARATIONS:
        if code not in (preparations or []):
            continue
        n = int(replicates or 0) * int(days or 0)
        conc = u"none" if code in BLANK_PREPARATIONS else ((concentrations or {}).get(code) or u"not set")
        rows.append({"level": label, "concentration": conc, "replicates": int(replicates or 0),
                     "days": int(days or 0), "preparations": n})
        total += n
    return rows, total


def spike_role(rec):
    """The role of a study's spiked replicates: chosen on an MDL (from the
    method's QC types: LFSM for a food or environmental matrix), LFB for
    the LFB kinds."""
    if rec.get("spike_role"):
        return rec["spike_role"]
    return LFB if rec.get("kind") in LFB_KINDS else u""
MDL_MONTHS = 24          # App. B Rev. 2 §4(b), §4(e)


def blank_role(profile):
    """The method blank by the method's name for it (its profile's), or None
    when the profile names none."""
    return me.blank_role(profile)


def injections(conn, method, roles, batches=None, since=None, until=None, matrix=None, profile=None):
    """[{"injection", "batch", "date", "values": {keyword: value | None}}]
    for the method's injections of `roles`, oldest first. A summed analyte is
    its total (its lr- / br- peaks are not listed); None = not detected. Where
    a run has no summed row for an analyte the `profile` sums from its isomers,
    the total is the sum of that analyte's peaks (isomers.total, the same sum
    the report shows)."""
    q = ("SELECT r.batch_id, r.injection_name, r.run_date, r.analyte, r.role, r.calc_conc, "
         "r.conc_qualifier, b.matrix FROM injection_results r LEFT JOIN batches b "
         "ON b.batch_id = r.batch_id WHERE r.method = ? AND r.qc_type IN (%s)"
         % ",".join("?" * len(roles)))
    args = [method] + list(roles)
    if batches:
        q += " AND r.batch_id IN (%s)" % ",".join("?" * len(batches))
        args += list(batches)
    if since:
        q += " AND r.run_date >= ?"
        args.append(since)
    if until:
        q += " AND r.run_date <= ?"
        args.append(until)
    out = {}
    peaks = {}
    library = _library()
    for batch, inj, date, name, role, conc, qual, bmatrix in conn.execute(q, args):
        if matrix and (bmatrix or u"") != matrix:
            continue
        if role == "internal standard":
            continue
        # keyed by run and injection: imported exports re-use names
        key = u"%s/%s" % (batch or u"", inj)
        rec = out.setdefault(key, {"injection": inj, "key": key, "batch": batch,
                                   "date": date or u"", "values": {}})
        if isomers.is_peak_name(name):
            peaks.setdefault(key, {})[name] = conc
            continue
        rec["values"][keyword_for(name, library)] = conc
    for key, found in peaks.items():
        values = out[key]["values"]
        for analyte in isomers.entries(profile or {}):
            kw = keyword_for(analyte, library)
            have = [found[n] for n in isomers.peaks_of(profile, analyte) if n in found]
            if have and kw not in values:
                values[kw] = isomers.total(have)
    return sorted(out.values(), key=lambda r: (r["date"], r["injection"]))


def _kept(rows, exclusions, kw):
    """The rows of one analyte left after the study's exclusions."""
    gone = set((e.get("injection"), e.get("analyte")) for e in exclusions or [])
    # an exclusion names the row's key ("WS-1/LRB") or, in an older record,
    # the bare injection name
    return [r for r in rows
            if not any((ident, a) in gone for ident in (r.get("key"), r["injection"]) for a in (kw, u"*"))]


def analytes(rows):
    return sorted(set(k for r in rows for k in r["values"]))


def calculate(kind, spikes, blanks=None, fortified=None, exclusions=None, existing=None,
              precision_limit=None):
    """{keyword: result} per method_studies, one analyte at a time.
    fortified = {keyword: concentration} (or one value for all); existing =
    {keyword: MDL in force} (mdl only); precision_limit(keyword, fortified)
    = {"spread": the RSD limit or None, "recovery_min", "recovery_max",
    "problem"}: the method profile's LFB tier at that level, its RSD limit
    the precision's and its recovery window the accuracy's (pa only; none
    given, or one not set: that part is not evaluated)."""
    out = {}
    for kw in analytes(spikes):
        rows = _kept(spikes, exclusions, kw)
        vals = [r["values"].get(kw) for r in rows]
        fort = fortified.get(kw) if isinstance(fortified, dict) else fortified
        if kind == "mdl":
            brows = _kept(blanks or [], exclusions, kw)
            out[kw] = ms.mdl_rev2([(v, r["date"], r["batch"]) for v, r in zip(vals, rows)],
                                  [r["values"].get(kw) for r in brows],
                                  existing=(existing or {}).get(kw))
        elif kind == "mrl":
            out[kw] = ms.mrl_confirmation(vals, fort) if fort else _no_fortified()
        elif kind == "pa":
            lim = (precision_limit(kw, fort) if precision_limit and fort else None) or {}
            window = (lim.get("recovery_min"), lim.get("recovery_max"))
            out[kw] = ms.precision_accuracy(vals, fort, lim.get("spread"), lim.get("problem"),
                                            window if None not in window else None) \
                if fort else _no_fortified()
        elif kind == "dl":
            out[kw] = ms.detection_limit([(v, r["date"]) for v, r in zip(vals, rows)])
    return out


def _no_fortified():
    return {"verdict": "not evaluated", "reason": u"no fortified concentration for this level"}


def applied_values(kind, results, fortified=None):
    """What an approved study writes to the method profile's Reporting
    Limits: an MDL study its MDLs; a passing MRL
    confirmation its fortified concentration as the RL. {keyword: {field:
    value}}; nothing for the other kinds."""
    out = {}
    for kw, res in sorted((results or {}).items()):
        # an MDL only where every App. B requirement was met (no notes) and
        # the replicates varied (identical results give s = 0: no MDL)
        if kind == "mdl" and res.get("verdict") == "calculated" and (res.get("mdl") or 0) > 1e-9:
            # as calculated: approval rounds it to the method's reporting format (settle)
            out[kw] = {"mdl": res["mdl"]}
        elif kind == "mrl" and res.get("verdict") == "pass":
            fort = fortified.get(kw) if isinstance(fortified, dict) else fortified
            if fort:
                out[kw] = {"rl": float(fort)}
    return out


def keepable(results):
    """The analytes whose MDL in force may be left unchanged (App. B Rev. 2
    §4(f): the new MDL within 0.5 to 2.0 times it, and fewer than 3 % of the
    method blanks above it; method_studies.mdl_rev2 judges it).
    `results` {keyword: result}."""
    return sorted(kw for kw, r in (results or {}).items() if isinstance(r, dict) and r.get("may_keep_existing"))


def settle(applied, profile, matrix, keep=(), keepable=()):
    """What approving an MDL study writes to the method profile, from what
    it calculated (`applied` {keyword: {"mdl": value}}):

      * each MDL rounded as the certificate prints it: the method x matrix
        report format's significant figures and rounding rule;
      * an analyte in `keep` keeps the MDL in force (nothing written), only
        where `keepable` lists it (App. B Rev. 2 §4(f)); any other is refused;
      * an MDL above the analyte's RL (typed, else its default from the
        lowest calibrator) raises the RL to that MDL, since MDLs move with
        lots and an RL is never below the MDL.

    {"applied", "kept": [keyword], "raised": {keyword: [RL before, RL]},
    "error": why nothing may be written, or ""}. A value other than an MDL
    (an MRL's RL) is written as it is."""
    from senaite.pfas import calibration_levels, report_format, rounding
    keep = sorted(set(k for k in keep or () if k))
    refused = [k for k in keep if k not in (keepable or ())]
    if refused:
        return {"applied": {}, "kept": [], "raised": {},
                "error": u"Keep existing is allowed only where the new MDL is within 0.5 to 2 times "
                         u"the one in force and under 3 %% of blanks are above it: not for %s." % u", ".join(refused)}
    fmt = report_format.resolve(profile, matrix)
    try:
        n = int(fmt.get("coa_sig_figs") or 3)
    except (TypeError, ValueError):
        n = 3
    rule = fmt.get("coa_rounding") or rounding.DEFAULT_RULE
    out, kept, raised = {}, [], {}
    for kw, vals in sorted((applied or {}).items()):
        vals = dict(vals or {})
        if "mdl" in vals:
            if kw in keep:
                kept.append(kw)
                vals.pop("mdl")
            else:
                mdl = float(rounding.round_sig(vals["mdl"], n, rule))
                vals["mdl"] = mdl
                rl = calibration_levels.reporting_limit(profile, matrix, kw)
                if rl is not None and mdl > rl and vals.get("rl") is None:
                    vals["rl"] = mdl
                    raised[kw] = [rl, mdl]
        if vals:
            out[kw] = vals
    return {"applied": out, "kept": kept, "raised": raised, "error": u""}


# ── an MDL study, run by run (the one-study page) ───────────────────────────

MONTHS = (u"Jan", u"Feb", u"Mar", u"Apr", u"May", u"Jun", u"Jul", u"Aug", u"Sep", u"Oct", u"Nov", u"Dec")


def short_date(iso):
    """"2026-11-12" as "12 Nov"; anything else as it came."""
    day = (iso or u"")[:10]
    try:
        y, m, d = [int(x) for x in day.split("-")]
        return u"%d %s" % (d, MONTHS[m - 1])
    except (ValueError, IndexError):
        return iso or u""


def plain_note(note):
    """A calculation note without the section reference it ends with
    ("... (§2(b), §3(b))")."""
    text = (note or u"").strip()
    cut = text.find(u" (\u00a7")
    return text[:cut].rstrip() if cut >= 0 else text


def runs_of(rows):
    """[{"batch", "date", "when"}] one per run of the rows, oldest first."""
    dates = {}
    for r in rows:
        b = r.get("batch") or u""
        d = r.get("date") or u""
        if b not in dates or (d and (not dates[b] or d < dates[b])):
            dates[b] = d
    return sorted(({"batch": b, "date": d, "when": short_date(d)} for b, d in dates.items()),
                  key=lambda x: (x["date"], x["batch"]))


def _is_number(v):
    return v is not None and v != u""


def run_cells(rows, exclusions, kw, runs):
    """One list per run of `runs`: the analyte's results from that run, each
    {"value", "excluded"}; value None = nothing detected."""
    kept = set(id(r) for r in _kept(rows, exclusions, kw))
    out = []
    for run in runs:
        out.append([{"value": r["values"].get(kw), "excluded": id(r) not in kept}
                    for r in rows if (r.get("batch") or u"") == run["batch"]])
    return out


def sample_text(role, counts, noun):
    """"LFB, 7 replicates": the role and how many samples were taken (counts
    = one number per spiking level; unlike numbers are listed by level)."""
    role = role or u""
    if not counts:
        return role or u"\u2014"
    nums = sorted(set(n for _l, n in counts))
    if len(nums) == 1:
        n = nums[0]
        body = u"%d %s%s" % (n, noun, u"" if n == 1 else u"s")
    else:
        body = u", ".join(u"%d%s" % (n, (u" at %s" % l) if l else u"") for l, n in counts)
    return u"%s, %s" % (role, body) if role else body


def mdl_level_view(spikes, blanks, results, exclusions, applied, existing, fmt):
    """One spiking level of an MDL study as the page draws it:

      {"spike_runs", "blank_runs": [{"batch", "date"}],
       "spike_rows": [{"kw", "cells", "n", "mean", "sd", "mdl_s", "mdl_b", "applied"}],
       "blank_rows": [{"kw", "cells", "highest"}],
       "mdl_b_line": the plain line where MDLb does not apply, else ""}

    cells are one list per run of {"text", "excluded"}. `applied` is what
    approval writes, `existing` the MDLs in force: an analyte with no new MDL
    shows the one in force."""
    spike_runs, blank_runs = runs_of(spikes), runs_of(blanks)
    spike_rows, blank_rows, no_b = [], [], []
    for kw, res in sorted((results or {}).items()):
        cells = [[{"text": fmt(c["value"]), "excluded": c["excluded"]} for c in run]
                 for run in run_cells(spikes, exclusions, kw, spike_runs)]
        mdl = ((applied or {}).get(kw) or {}).get("mdl")
        if mdl is None:
            mdl = (existing or {}).get(kw)
        spike_rows.append({"kw": kw, "cells": cells, "n": res.get("n_spikes", res.get("n")),
                           "mean": fmt(res.get("mean_spikes", res.get("mean"))),
                           "sd": fmt(res.get("sd_spikes", res.get("sd"))),
                           "mdl_s": fmt(res.get("mdl_s")),
                           "mdl_b": fmt(res["mdl_b"]) if res.get("mdl_b") is not None else u"none",
                           "applied": fmt(mdl)})
        if res.get("mdl_b") is None:
            no_b.append(kw)
        bcells, numbers = [], []
        for run in run_cells(blanks, exclusions, kw, blank_runs):
            bcells.append([{"text": u"ND" if not _is_number(c["value"]) else fmt(c["value"]),
                            "excluded": c["excluded"]} for c in run])
            numbers += [c["value"] for c in run if _is_number(c["value"]) and not c["excluded"]]
        blank_rows.append({"kw": kw, "cells": bcells, "highest": fmt(max(numbers)) if numbers else u"ND"})
    line = u""
    if no_b and len(no_b) == len(spike_rows):
        line = u"No blank gave a number, so MDLb does not apply and the MDL comes from the spikes alone."
    elif no_b:
        line = u"MDLb does not apply to %s: no blank gave a number there." % u", ".join(no_b)
    ns = [r["n"] for r in spike_rows if r["n"]]
    return {"spike_runs": spike_runs, "blank_runs": blank_runs, "spike_rows": spike_rows,
            "blank_rows": blank_rows, "mdl_b_line": line, "n": max(ns) if ns else None}


def note_lines(results):
    """[u"PFOA, PFBS: the note"]: each distinct calculation note of an MDL
    study's levels once, with the analytes it is about (or "Every analyte"),
    its section reference left out."""
    by_note, every = {}, set()
    for res in (results or {}).values():
        for kw, r in res.items():
            every.add(kw)
            for note in r.get("notes") or []:
                by_note.setdefault(plain_note(note), set()).add(kw)
    out = []
    for note in sorted(by_note):
        names = sorted(by_note[note])
        who = u"Every analyte" if set(names) == every and len(names) > 1 else u", ".join(names)
        out.append(u"%s: %s." % (who, note))
    return out


# ── several spiking levels: results per level ───────────────────────────────

def calculate_levels(kind, spikes, blanks=None, fortified=None, exclusions=None, existing=None,
                     precision_limit=None):
    """{level: {keyword: result}}: each spike row carries its "level" (the
    extraction batch member's label); `fortified` = {level: value or
    {keyword: value}}. Blanks are shared by every level."""
    out = {}
    for level in sorted(set(r.get("level") or u"" for r in spikes)):
        rows = [r for r in spikes if (r.get("level") or u"") == level]
        out[level] = calculate(kind, rows, blanks, (fortified or {}).get(level), exclusions, existing,
                               precision_limit)
    return out


def applied_by_level(kind, results, fortified=None):
    """What approval writes, from per-level results. An MDL comes from ONE
    spiking level (App. B Rev. 2 §4(b): "only data with the same spiking
    level"); several levels apply nothing. A confirmed MRL: per analyte, the
    lowest level that passed (its fortified concentration as the RL)."""
    results = results or {}
    if kind == "mdl":
        if len(results) != 1:
            return {}
        (level, res), = results.items()
        return applied_values("mdl", res)
    if kind == "mrl":
        out = {}
        ranked = sorted(results.items(), key=lambda kv: _fort_of((fortified or {}).get(kv[0]), None) or 0)
        for level, res in ranked:
            for kw, vals in applied_values("mrl", res, (fortified or {}).get(level)).items():
                out.setdefault(kw, vals)
        return out
    return {}


def _fort_of(f, kw):
    if isinstance(f, dict):
        vals = [v for v in f.values() if v]
        return min(vals) if vals else None
    return f


# ── proficiency tests ───────────────────────────────────────────────────────

def pt_results(entries):
    """{keyword: {"reported", "assigned", "verdict"}} from the page's rows,
    keeping only analytes something was entered for."""
    out = {}
    for kw, e in sorted((entries or {}).items()):
        e = dict((k, (u"%s" % (v or u"")).strip()) for k, v in (e or {}).items())
        if any(e.get(k) for k in ("reported", "assigned", "verdict")):
            out[kw] = {"reported": e.get("reported", u""), "assigned": e.get("assigned", u""),
                       "verdict": e.get("verdict", u"")}
    return out


def pt_problems(pt, certificate_present):
    """What holds a PT study's approval: the provider's certificate ("store a
    passing certificate with each study"), the round, at least one analyte,
    and the provider's verdict on each."""
    pt = pt or {}
    out = []
    if not certificate_present:
        out.append(u"Attach the provider's certificate.")
    if not (pt.get("provider") or u"").strip() or not (pt.get("round") or u"").strip():
        out.append(u"State the provider and the round.")
    results = pt.get("results") or {}
    if not results:
        out.append(u"Enter the reported analytes.")
    valid = set(k for k, _l in PT_VERDICTS)
    missing = sorted(kw for kw, r in results.items() if r.get("verdict") not in valid)
    if missing:
        out.append(u"The provider's verdict is missing for %s." % u", ".join(missing))
    return out


def pt_verdict(pt):
    results = (pt or {}).get("results") or {}
    if not results:
        return u"not evaluated"
    return u"pass" if all(r.get("verdict") == u"acceptable" for r in results.values()) else u"fail"
